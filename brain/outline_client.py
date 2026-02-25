import httpx
from typing import Optional

INBOX_NAME  = "📥 Inbox"
LIBRARY_NAME = "📚 Library"


class OutlineClient:
    def __init__(self, base_url: str, token: str):
        self.base    = base_url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        self._inbox_id:   Optional[str] = None
        self._library_id: Optional[str] = None
        self._topic_cache: dict[str, str] = {}

    async def _post(self, path: str, data: dict) -> dict:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(f"{self.base}/api/{path}", json=data, headers=self.headers)
            r.raise_for_status()
            return r.json()

    async def ensure_collections(self) -> tuple[str, str]:
        if self._inbox_id and self._library_id:
            return self._inbox_id, self._library_id
        cols = (await self._post("collections.list", {})).get("data", [])
        by_name = {c["name"]: c["id"] for c in cols}
        self._inbox_id   = by_name.get(INBOX_NAME)   or (await self._post("collections.create", {"name": INBOX_NAME,   "icon": "collection", "permission": "read_write"}))["data"]["id"]
        self._library_id = by_name.get(LIBRARY_NAME) or (await self._post("collections.create", {"name": LIBRARY_NAME, "icon": "collection", "permission": "read_write"}))["data"]["id"]
        return self._inbox_id, self._library_id

    async def _get_or_create_topic(self, collection_id: str, topic: str) -> str:
        key = f"{collection_id}:{topic}"
        if key in self._topic_cache:
            return self._topic_cache[key]
        res  = await self._post("documents.search", {"query": topic, "collectionId": collection_id})
        for item in res.get("data", []):
            doc = item.get("document", {})
            if doc.get("title") == topic and not doc.get("parentDocumentId"):
                self._topic_cache[key] = doc["id"]
                return doc["id"]
        doc_id = (await self._post("documents.create", {
            "collectionId": collection_id,
            "title": topic,
            "text": f"# {topic}",
            "publish": True,
        }))["data"]["id"]
        self._topic_cache[key] = doc_id
        return doc_id

    async def create_document(self, collection_id: str, title: str, text: str, topic: Optional[str] = None) -> dict:
        parent_id = None
        if topic and topic.lower() != "other":
            parent_id = await self._get_or_create_topic(collection_id, topic)
        payload = {"collectionId": collection_id, "title": title, "text": text, "publish": True}
        if parent_id:
            payload["parentDocumentId"] = parent_id
        return (await self._post("documents.create", payload))["data"]
