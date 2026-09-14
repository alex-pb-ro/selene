from selene.config.context_mode import SeleneAgentContext, SeleneAgentMode

if __name__ == "__main__":
    print("---------- Available modes: ----------")
    for mode_name in SeleneAgentMode.list_registered_mode_names():
        mode = SeleneAgentMode.load(mode_name)
        mode.print_overview()
        print("\n")
    print("---------- Available contexts: ----------")
    for context_name in SeleneAgentContext.list_registered_context_names():
        context = SeleneAgentContext.load(context_name)
        context.print_overview()
        print("\n")
