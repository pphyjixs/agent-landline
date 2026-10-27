"""DSH-specific text injection and reading; no ASR, telephone or TTS imports."""
import json
from pathlib import Path
from browser_mcp import BrowserMCP


class DshWebAdapter:
    def __init__(self, options, root):
        self.options, self.root = options, Path(root)
        self.mcp = None
        self.session = options.get('session_id', '')

    def connect(self):
        self.mcp = BrowserMCP(self.options, self.root)
        target = json.dumps(self.options['url'])
        # The installed extension initially attaches its welcome tab. Add only
        # already-open DSH tabs to that tab group, using the extension's own API.
        self.mcp.run('''async current => {
            const ext = current.context().pages().find(p => p.url().startsWith('chrome-extension://mmlmfjhmonkocbjadbfplnigmagldckm/'));
            if (!ext) return false;
            return await ext.evaluate(async target => {
                const here = await chrome.tabs.getCurrent();
                if (!here || here.groupId < 0) return false;
                const tabs = await chrome.tabs.query({});
                for (const tab of tabs) {
                    try {
                        if (new URL(tab.url).origin === new URL(target).origin && tab.groupId !== here.groupId)
                            await chrome.tabs.group({groupId:here.groupId,tabIds:[tab.id]});
                    } catch (error) { /* Non-web tabs cannot be DSH pages. */ }
                }
                return true;
            }, TARGET);
        }'''.replace('TARGET', target), timeout=60)
        state = self.snapshot()
        if not state['session']:
            raise RuntimeError('请先在 Edge 中打开一个已有的 DSH 对话，再启动程序')
        self.session = state['session']
        return state

    def run(self, code):
        return self.mcp.run('''async current => {
            const origin = new URL(TARGET).origin;
            const candidates = [];
            for (const page of current.context().pages()) {
                try {
                    if (new URL(page.url()).origin !== origin) continue;
                    const ids = await page.locator('[data-conversation-content]').evaluateAll(ns => ns.map(n => n.dataset.conversationSession).filter(Boolean));
                    if (SESSION ? ids.includes(SESSION) : ids.length === 1) candidates.push(page);
                } catch (error) { /* Tab may have closed during enumeration. */ }
            }
            if (candidates.length !== 1) throw new Error('Open exactly one bound DSH conversation');
            const page = candidates[0];
            return await (BODY)(page);
        }'''.replace('TARGET', json.dumps(self.options['url']))
            .replace('SESSION', json.dumps(self.session)).replace('BODY', code),
            timeout=self.options['operation_timeout_seconds'])

    def snapshot(self):
        function = (Path(__file__).with_name('dsh_page_state.js')).read_text(encoding='utf-8')
        return self.run('async page => page.evaluate(' + function + ', ' +
                        json.dumps({**self.options, 'bound_session': self.session}) + ')')

    def send(self, text):
        """One click only; an ambiguous result must never be automatically retried."""
        opts = json.dumps(self.options)
        return self.run('''async page => {
            const opts = OPTIONS;
            const root = page.locator('[data-conversation-content][data-conversation-session=' + JSON.stringify(SESSION_ID) + ']');
            if (await root.locator(opts.busy_selector).filter({visible:true}).count()) throw new Error('DSH busy');
            const editor = root.locator(opts.editor_selector);
            if (await editor.count() !== 1) throw new Error('Composer missing');
            if ((await editor.innerText()).trim()) throw new Error('Existing draft must be kept');
            if (await root.locator('[data-composer-chip], [data-composer-quote], [data-composer-command], [data-composer-card] img, [data-composer-card] [data-file-card]').count()) throw new Error('Composer contains attachments');
            const before = await root.locator(opts.user_selector).evaluateAll(ns => ns.map(n => n.dataset.chatNodeKey));
            await editor.fill(TEXT);
            const send = root.locator(opts.send_selector).filter({visible:true});
            if (await send.count() !== 1) throw new Error('Send button unavailable');
            // Lexical/React may enable the button after the fill input event.
            // Playwright click waits for it without issuing a second click.
            await send.click({timeout:5000});
            try {
                await page.waitForFunction(({session, selector, before, text}) => {
                    const root = [...document.querySelectorAll('[data-conversation-content]')].find(n => n.dataset.conversationSession === session);
                    return root && [...root.querySelectorAll(selector)].some(n => !before.includes(n.dataset.chatNodeKey) && n.textContent.includes(text));
                }, {session:SESSION_ID, selector:opts.user_selector, before, text:TEXT}, {timeout:8000});
            } catch (error) { return {accepted:false, uncertain:true}; }
            const echo = await root.locator(opts.user_selector).evaluateAll((ns, before) => {
                const n = ns.find(n => !before.includes(n.dataset.chatNodeKey));
                return n ? {user_key:n.dataset.chatNodeKey, turn:n.dataset.chatTurn} : {};
            }, before);
            return {accepted:true, uncertain:false, ...echo};
        }'''.replace('OPTIONS', opts).replace('SESSION_ID', json.dumps(self.session))
            .replace('TEXT', json.dumps(text)))

    def close(self):
        if self.mcp:
            self.mcp.close()
