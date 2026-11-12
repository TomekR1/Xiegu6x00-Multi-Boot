"""What an image is made of: pieces placed at offsets. The same plan writes a file or a card."""
import hashlib
import json
import os

CHUNK = 4 << 20


class Zero:
    def __init__(self, length):
        self.length = length

    def chunks(self):
        n = self.length
        z = b"\x00" * min(CHUNK, n)
        while n:
            k = min(CHUNK, n)
            yield z[:k]
            n -= k

    def to_json(self):
        return {"zero": self.length}


class Data:
    def __init__(self, data, blob=None):
        self.data = bytes(data)
        self.length = len(self.data)
        self.blob = blob     # file holding the same bytes, for a plan handed to another process

    def chunks(self):
        for i in range(0, self.length, CHUNK):
            yield self.data[i:i + CHUNK]

    def to_json(self):
        return {"file": self.blob, "offset": 0, "length": self.length}


class FileRange:
    def __init__(self, path, offset, length):
        self.path, self.offset, self.length = path, offset, length

    def chunks(self):
        with open(self.path, "rb") as f:
            f.seek(self.offset)
            n = self.length
            while n:
                d = f.read(min(CHUNK, n))
                if not d:
                    raise IOError(f"{self.path}: ends early")
                yield d
                n -= len(d)

    def to_json(self):
        return {"file": self.path, "offset": self.offset, "length": self.length}


def from_json(j):
    if "zero" in j:
        return Zero(j["zero"])
    return FileRange(j["file"], j["offset"], j["length"])


class Plan:
    """size bytes, with pieces [(offset, piece)]; what no piece covers is left as it is (zeros in a file)"""

    def __init__(self, size):
        self.size = size
        self.pieces = []
        self.info = {}

    def add(self, offset, piece):
        if piece.length:
            self.pieces.append((offset, piece))

    def check(self):
        self.pieces.sort(key=lambda p: p[0])
        end = 0
        for off, p in self.pieces:
            if off < end:
                raise ValueError(f"pieces overlap at {off}")
            if off % 512 or p.length % 512:
                raise ValueError(f"piece at {off} ({p.length} bytes) not on 512-byte sectors")
            end = off + p.length
        if end > self.size:
            raise ValueError("pieces run past the end of the image")

    def written_bytes(self):
        return sum(p.length for _, p in self.pieces)

    def save(self, path, blob_dir):
        """The plan as JSON, with the in-memory pieces as files in blob_dir (for the elevated writer)"""
        os.makedirs(blob_dir, exist_ok=True)
        out = []
        for i, (off, p) in enumerate(self.pieces):
            if isinstance(p, Data) and not p.blob:
                p.blob = os.path.join(blob_dir, f"piece{i:04d}.bin")
                with open(p.blob, "wb") as f:
                    f.write(p.data)
            out.append([off, p.to_json()])
        with open(path, "w") as f:
            json.dump({"size": self.size, "pieces": out, "info": self.info}, f)

    @staticmethod
    def load(path):
        with open(path) as f:
            j = json.load(f)
        plan = Plan(j["size"])
        plan.info = j.get("info", {})
        for off, pj in j["pieces"]:
            plan.add(off, from_json(pj))
        plan.check()
        return plan

    def digest(self):
        """SHA-256 of the written pieces, in order: what a read-back must give again"""
        h = hashlib.sha256()
        for _, p in self.pieces:
            for c in p.chunks():
                h.update(c)
        return h.hexdigest()
