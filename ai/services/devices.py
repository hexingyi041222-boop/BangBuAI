from dataclasses import dataclass
from threading import Lock
from time import time
@dataclass
class DeviceBinding:
    device_id: str; user_id: str; bound_at: float; status: str = 'active'
class DeviceBindingStore:
    def __init__(self): self.items: dict[str, DeviceBinding] = {}; self.lock = Lock()
    def bind(self, device_id: str, user_id: str):
        with self.lock: self.items[device_id] = DeviceBinding(device_id, user_id, time()); return self.items[device_id]
    def unbind(self, device_id: str):
        with self.lock:
            item = self.items.get(device_id)
            if item: item.status = 'unbound'
            return item
    def get(self, device_id: str): return self.items.get(device_id)
    def list_user(self, user_id: str): return [x for x in self.items.values() if x.user_id == user_id and x.status == 'active']
device_bindings = DeviceBindingStore()
