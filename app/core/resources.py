from typing import Any, Optional, Dict

class ResourceRegistry:
    """Tracks camera and serial ownership across run tabs.
    Moved from run_tab.py to decouple UI from Resource Management.
    """

    def __init__(self):
        self._camera_owners: Dict[int, Any] = {}
        self._serial_owners: Dict[str, Any] = {}

    def claim_camera(self, owner: Any, index: int) -> tuple[bool, Optional[Any]]:
        idx = int(index)
        existing = self._camera_owners.get(idx)
        if existing is not None and existing is not owner:
            return False, existing
        self._camera_owners[idx] = owner
        return True, existing

    def release_camera(self, owner: Any, index: Optional[int] = None) -> None:
        if index is not None:
            idx = int(index)
            if self._camera_owners.get(idx) is owner:
                self._camera_owners.pop(idx, None)
            return
        for idx, current in list(self._camera_owners.items()):
            if current is owner:
                self._camera_owners.pop(idx, None)

    def claim_serial(self, owner: Any, port: str) -> tuple[bool, Optional[Any]]:
        key = port.strip()
        existing = self._serial_owners.get(key)
        if existing is not None and existing is not owner:
            return False, existing
        self._serial_owners[key] = owner
        return True, existing

    def release_serial(self, owner: Any, port: Optional[str] = None) -> None:
        if port is not None:
            key = port.strip()
            if self._serial_owners.get(key) is owner:
                self._serial_owners.pop(key, None)
            return
        for key, current in list(self._serial_owners.items()):
            if current is owner:
                self._serial_owners.pop(key, None)

    def release_all(self, owner: Any) -> None:
        self.release_camera(owner)
        self.release_serial(owner)
