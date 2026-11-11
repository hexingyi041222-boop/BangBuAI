from enum import Enum
class Role(str, Enum): user='user'; caregiver='caregiver'; admin='admin'; device='device'
class PermissionMatrix:
    matrix = {Role.user: {'chat:write','chat:read','session:end'}, Role.caregiver: {'chat:read','emotion:read','risk:read','risk:handle'}, Role.admin: {'*'}, Role.device: {'chat:write','mqtt:publish'}}
    @classmethod
    def allows(cls, role: str, permission: str) -> bool:
        try: allowed = cls.matrix[Role(role)]
        except (KeyError, ValueError): return False
        return '*' in allowed or permission in allowed
