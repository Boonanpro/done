"""Verified registrant contacts used for every DAN domain purchase."""
from __future__ import annotations

from typing import Any, Optional

from app.services.encryption import get_encryption_service
from app.services.supabase_client import get_supabase_client

TABLE = "domain_registrant_profile"
SETUP_TABLE = "domain_setup_registrant"


class DomainRegistrantProfileService:
    def __init__(self) -> None:
        self.supabase = get_supabase_client().client
        self.encryption = get_encryption_service()

    @staticmethod
    def _to_registrar_contact(contact: dict[str, Any]) -> dict[str, Any]:
        """Normalize Name.com contact fields to the Cloudflare Registrar shape."""
        return {
            "email": contact["email"],
            "phone": contact["phone"],
            "postal_info": {
                "name": f"{contact['firstName']} {contact['lastName']}".strip(),
                "organization": contact.get("companyName") or "",
                "address": {
                    "street": contact["address1"],
                    "city": contact["city"],
                    "state": contact["state"],
                    "postal_code": contact["zip"],
                    "country_code": contact["country"],
                },
            },
        }

    async def get(self, user_id: str) -> Optional[dict[str, Any]]:
        row = self.supabase.table(TABLE).select("encrypted_contact").eq("user_id", user_id).execute().data
        if not row:
            return None
        return self.encryption.decrypt_dict(row[0]["encrypted_contact"].encode("utf-8"))

    async def save_from_namecom_domain(self, user_id: str, source_domain: str) -> dict[str, Any]:
        """Import the already verified registrant contact once, then use that copy."""
        from app.tools.publish_site.namecom_registrar import get_namecom_registrar
        data = await (await get_namecom_registrar(user_id))._request("GET", f"/domains/{source_domain}")
        contact = ((data.get("contacts") or {}).get("registrant") or {})
        required = ("firstName", "lastName", "email", "phone", "address1", "city", "state", "zip", "country")
        if not all(contact.get(k) for k in required):
            raise RuntimeError("The existing registrar contact is incomplete; a complete registrant profile is required.")
        normalized = self._to_registrar_contact(contact)
        encrypted = self.encryption.encrypt_dict(normalized).decode("utf-8")
        label = f"{contact['firstName']} {contact['lastName']} / {contact['email'][:1]}***"
        row = {"user_id": user_id, "encrypted_contact": encrypted, "masked_label": label, "source_domain": source_domain}
        self.supabase.table(TABLE).upsert(row, on_conflict="user_id").execute()
        return normalized

    async def get_or_bootstrap(self, user_id: str) -> dict[str, Any]:
        contact = await self.get(user_id)
        if contact:
            return contact
        # paina.info is the already verified account-owned registrant.  This is
        # a one-time migration, not a runtime dependency on the old domain.
        return await self.save_from_namecom_domain(user_id, "paina.info")

    async def save_for_setup(self, token: str, contact: dict[str, Any]) -> None:
        postal = contact.get("postal_info") or {}
        address = postal.get("address") or {}
        required = (contact.get("email"), contact.get("phone"), postal.get("name"), address.get("street"), address.get("city"), address.get("state"), address.get("postal_code"), address.get("country_code"))
        if not all(required):
            raise ValueError("Complete registrant information is required.")
        encrypted = self.encryption.encrypt_dict(contact).decode("utf-8")
        self.supabase.table(SETUP_TABLE).upsert({"domain_setup_token": token, "encrypted_contact": encrypted}, on_conflict="domain_setup_token").execute()

    async def get_for_setup(self, token: str) -> Optional[dict[str, Any]]:
        rows = self.supabase.table(SETUP_TABLE).select("encrypted_contact").eq("domain_setup_token", token).execute().data
        return self.encryption.decrypt_dict(rows[0]["encrypted_contact"].encode("utf-8")) if rows else None


_service: Optional[DomainRegistrantProfileService] = None


def get_domain_registrant_profile_service() -> DomainRegistrantProfileService:
    global _service
    if _service is None:
        _service = DomainRegistrantProfileService()
    return _service
