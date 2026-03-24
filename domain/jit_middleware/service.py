from domain.jit_middleware.models import EnforcementPayload, JITRequest


class JITService:
    @staticmethod
    def generate_enforcements(
        req: JITRequest,
        ipaddrgroup_name: str | None = None,
    ) -> list[EnforcementPayload]:
        is_login = req.action.upper() == "LOGIN"
        if is_login:
            ip_expression = [{"resource_type": "IPAddressExpression", "ip_addresses": [req.source_ip]}]
        else:
            # remove_ip signals the NSX client to surgically remove this specific IP
            # rather than overwriting the entire ip_addresses list.
            ip_expression = [{"resource_type": "IPAddressExpression", "ip_addresses": [], "remove_ip": req.source_ip}]

        gfw_group = f"JIT_Edge_{req.target_app}_Authorized_IPs"
        dfw_group = f"JIT_Workload_{req.target_app}_Authorized_IPs"

        nsx_gfw = EnforcementPayload(
            system="vDefend Gateway Firewall",
            method="PATCH",
            url=f"https://nsx-manager.lab/policy/api/v1/infra/domains/default/groups/{gfw_group}",
            payload={
                "display_name": gfw_group,
                "expression": ip_expression,
            },
        )

        nsx_dfw = EnforcementPayload(
            system="vDefend Distributed Firewall",
            method="PATCH",
            url=f"https://nsx-manager.lab/policy/api/v1/infra/domains/default/groups/{dfw_group}",
            payload={
                "display_name": dfw_group,
                "expression": ip_expression,
            },
        )

        # Use the mapped IP group name if one was provided via policy mapping;
        # fall back to the default naming convention otherwise.
        avi_group = ipaddrgroup_name or f"JIT_{req.target_app}_Allowed"

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
            url=f"https://avi-controller.lab/api/ipaddrgroup?name={avi_group}",
            payload=avi_payload,
        )

        return [nsx_gfw, nsx_dfw, avi_lb]
