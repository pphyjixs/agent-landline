(opts) => {
    const roots = [...document.querySelectorAll('[data-conversation-content]')];
    const root = opts.bound_session
        ? roots.find(n => n.dataset.conversationSession === opts.bound_session)
        : roots.find(n => n.dataset.conversationSession);
    if (!root) throw new Error('Bound conversation is not open');
    const visible = n => n.getClientRects().length > 0;
    const busy = [...root.querySelectorAll(opts.busy_selector)].some(visible);
    const candidates = [...root.querySelectorAll(opts.assistant_selector)].filter(n =>
        n.dataset.chatGroupPart !== 'reasoning' && !n.hasAttribute('data-turn-process-member') &&
        !n.closest('[data-step-process]'));
    const replies = candidates.map(n => {
        const clone = n.cloneNode(true);
        clone.querySelectorAll('button, details, [data-variant="think"], [data-turn-process-inline], [data-turn-tail], script, style')
            .forEach(e => e.remove());
        clone.querySelectorAll('p, li, h1, h2, h3, h4, h5, h6, pre, tr').forEach(e => e.append('\n'));
        return {key:n.dataset.chatNodeKey, turn:n.dataset.chatTurn,
            text:clone.textContent.trim(), streaming:!!n.querySelector('[data-streaming="true"]')};
    }).filter(n => n.text);
    // Only the final response in the newest turn is spoken. Historical paging
    // and intermediate commentary must never trigger new telephone playback.
    const latest = replies.at(-1) || null;
    const users = [...root.querySelectorAll(opts.user_selector)].map(n => {
        const text = n.querySelector('[data-message-bubble]') || n;
        return {key:n.dataset.chatNodeKey, turn:n.dataset.chatTurn, text:text.textContent.trim()};
    });
    const user = users.at(-1);
    const activeTurn = [...root.querySelectorAll('[data-chat-turn]')].at(-1)?.dataset.chatTurn || '';
    const errors = [...root.querySelectorAll('[data-chat-flow-kind="turn-error"]')];
    return {url:location.href, session:root.dataset.conversationSession,
        busy, reply:latest, users, userKey:user?.key || '', activeTurn,
        error:errors.at(-1)?.dataset.chatNodeKey || '',
        editor:root.querySelectorAll(opts.editor_selector).length,
        draft:!!root.querySelector(opts.editor_selector)?.textContent.trim(),
        sendButtons:[...root.querySelectorAll(opts.send_selector)].filter(visible).length};
}
