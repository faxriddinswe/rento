from app.services.storage import ObjectInfo, PresignedPost


class InMemoryStorage:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}

    async def ping(self) -> None: ...
    async def ensure_bucket(self) -> None: ...

    async def presign_post(self, key, content_type, max_bytes, expires=600):
        return PresignedPost(url="http://fake-storage/upload", fields={"key": key}, key=key)

    async def presign_get(self, key, expires=600):
        return f"http://fake-storage/{key}?sig=1"

    async def head(self, key):
        o = self.objects.get(key)
        return None if o is None else ObjectInfo(size=len(o[0]), content_type=o[1])

    async def put(self, key, data, content_type):
        self.objects[key] = (data, content_type)

    async def get(self, key):
        return self.objects[key][0]
