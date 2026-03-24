from domain.jit_middleware.models import EnforcementPayload, JITRequest


class JITService:
    @staticmethod
    def generate_enforcements(
        req: JITRequest,
        ipaddrgroup_name: str | None = None,
        nsx_host: str | None = None,
        avi_host: str | None = None,
    ) -> list[EnforcementPayload]:
        is_login = req.action.upper() == "LOGIN"
        if is_login:
            ip_expression = [{"resource_type": "IPAddressExpression", "ip_addresses": [req.source_ip]}]
        else:
            # remove_ip signals the NSX client to surgically remove this specific IP
            # rather than overwriting the entire ip_addresses list.
            ip_expression = [{"resource_type": "IPAddressExpression", "ip_addresses": [], "remove_ip": req.source_ip}]

        # Derive the group IDs using the same convention as vDefend onboarding:
        #   HR_APP_01 → prefix "HR" → "HR-JIT-active-users-ipaddr"
        prefix = req.target_app.split("_")[0]
        jit_group = f"{prefix}-JIT-active-users-ipaddr"

        nsx_base = (nsx_host or "https://nsx-manager.lab").rstrip("/")

        nsx_gfw = EnforcementPayload(
            system="vDefend Gateway Firewall",
            method="PATCH",
            url=f"{nsx_base}/policy/api/v1/infra/domains/default/groups/{jit_group}",
            payload={
                "display_name": jit_group,
                "expression": ip_expression,
            },
        )

        nsx_dfw = EnforcementPayload(
            system="vDefend Distributed Firewall",
            method="PATCH",
            url=f"{nsx_base}/policy/api/v1/infra/domains/default/groups/{jit_group}",
            payload={
                "display_name": jit_group,
                "expression": ip_expression,
            },
        )

        # Use the mapped IP group name if one was provided via policy mapping;
        # fall back to the same prefix convention otherwise.
        avi_group = ipaddrgroup_name or f"{prefix}-JIT-active-users-ipaddr"
        avi_base = (avi_host or "https://avi-controller.lab").rstrip("/")

        avi_payload: dict
        if is_login:
            avi_payload = {
                "name": avi_group,
                "addrs": [{"addr": req.source_ip, "type": "V4"}],
            }
        else:
            # remove_addr signals the AVI client to surgically remove this
            # specific IP rather than overwriting the entire addrs list.
            avi_payload = {
                "name": avi_group,
                "addrs": [],
                "remove_addr": req.source_ip,
            }

        avi_lb = EnforcementPayload(
            system="AVI Load Balancer",
            method="PUT",
            url=f"{avi_base}/api/ipaddrgroup?name={avi_group}",
            payload=avi_payload,
        )

        return [nsx_gfw, nsx_dfw, avi_lb]
