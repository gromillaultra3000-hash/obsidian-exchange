class StorageAdapter:
    def initialize(self, db_path: str): raise NotImplementedError
    def save_record(self, profile_id: str, collection: str, record_id: str, payload: dict): raise NotImplementedError
    def load_collection(self, profile_id: str, collection: str) -> list[dict]: raise NotImplementedError
    def delete_record(self, profile_id: str, collection: str, record_id: str): raise NotImplementedError
    def clear_collection(self, profile_id: str, collection: str): raise NotImplementedError
    def clear_profile(self, profile_id: str): raise NotImplementedError
    def list_collections(self, profile_id: str) -> list[str]: raise NotImplementedError
    def health(self) -> dict: raise NotImplementedError
