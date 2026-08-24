class SecurityStatusBuilder:
    def build(self, runtime):
        return runtime.get_security_state()
