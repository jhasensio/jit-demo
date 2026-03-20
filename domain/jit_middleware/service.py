from domain.jit_middleware.models import EnforcementPayload, JITRequest


class JITService:
    @staticmethod
    def generate_enforcements(req: JITRequest) -> list[EnforcementPayload]:
        is_login = req.action.upper() == "LOGIN"
        ip_expression = (
            [{"resource_type": "IPAddressExpression", "ip_addresses": [req.source_ip]}]
            if is_login
            else [{"resource_type": "IPAddressExpression", "ip_addresses": []}]
        )

        nsx_gfw = EnforcementPayload(
            system="NSX Gateway Firewall",
            method="PATCH",
            url="https://nsx-manager.lab/policy/api/v1/infra/domains/default/groups/JIT_Edge_Authorized_IPs",
            payload={
                "display_name": "JIT_Edge_Authorized_IPs",
                "expression": ip_expression,
            },
        )

        nsx_dfw = EnforcementPayload(
            system="NSX Distributed Firewall",
            method="PATCH",
            url="https://nsx-manager.lab/policy/api/v1/infra/domains/default/groups/JIT_Workload_Authorized_IPs",
            payload={
                "display_name": "JIT_Workload_Authorized_IPs",
                "expression": ip_expression,
            },
        )

        avi_payload: dict
        if is_login:
            avi_payload = {
                "name": f"JIT_{req.target_app}_Allowed",
                "addrs": [{"addr": req.source_ip, "type": "V4"}],
            }
        else:
            # remove_addr signals the AVI client to surgically remove this
            # specific IP rather than overwriting the entire addrs list.
            avi_payload = {
                "name": f"JIT_{req.target_app}_Allowed",
                "addrs": [],
                "remove_addr": req.source_ip,
            }

        avi_lb = EnforcementPayload(
            system="AVI Load Balancer",
            method="PUT",
            url=f"https://avi-controller.lab/api/ipaddrgroup?name=JIT_{req.target_app}_Allowed",
            payload=avi_payload,
        )

        return [nsx_gfw, nsx_dfw, avi_lb]
