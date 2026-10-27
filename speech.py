"""Plain-text preparation and durable, per-session reply deduplication."""
import json
from pathlib import Path
import re


def speech_text(text):
    text = re.sub(r'```[\s\S]*?```', '（代码内容请查看网页。）', text)
    text = re.sub(r'!\[[^\]]*\]\([^)]*\)', '', text)
    text = re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', text)
    text = re.sub(r'https?://\S+', '', text)
    text = re.sub(r'(?m)^\s{0,3}(?:#{1,6}|>|[-*+])\s+', '', text)
    text = re.sub(r'[*_`~]', '', text)
    return re.sub(r'\n{3,}', '\n\n', text).strip()


def chunks(text, limit=100):
    result, current = [], ''
    for piece in re.split(r'(?<=[。！？!?；;\n])', text):
        if current and len(current) + len(piece) > limit:
            result.append(current.strip()); current = ''
        while len(piece) > limit:
            result.append(piece[:limit].strip()); piece = piece[limit:]
        current += piece
    if current.strip():
        result.append(current.strip())
    return [part for part in result if part]


def sentence_chunks(text, limit=40, first_limit=20):
    """Keep sentence boundaries; shorten the first playable phrase without loss."""
    result = []
    for sentence in re.split(r'(?<=[。！？!?；;\n])', text):
        while sentence:
            bound = first_limit if not result else limit
            if len(sentence) <= bound:
                part, sentence = sentence, ''
            else:
                prefix = sentence[:bound]
                cuts = [match.end() for match in re.finditer(r'[，,、：:\s]', prefix)]
                cut = next((p for p in reversed(cuts) if p >= bound // 2), bound)
                part, sentence = sentence[:cut], sentence[cut:]
            if part.strip():
                result.append(part.strip())
    return result


class ReplyLedger:
    def __init__(self, path):
        self.path = Path(path)
        # A corrupt ledger must be repaired explicitly, never silently replayed.
        self.seen = json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else {}

    @staticmethod
    def key(session, reply):
        return f"{session}:{reply['turn']}"

    def contains(self, session, reply):
        return self.key(session, reply) in self.seen

    def mark(self, session, reply, outcome):
        self.seen[self.key(session, reply)] = {'node':reply['key'], 'outcome':outcome}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix('.tmp')
        temp.write_text(json.dumps(self.seen, ensure_ascii=False, indent=2), encoding='utf-8')
        temp.replace(self.path)
