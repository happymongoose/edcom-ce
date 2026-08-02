export function canViewAutomationDiagnostics(props) {
  return Boolean(
    (props.user && props.user.admin) ||
    props.loggedInImpersonate ||
    (props.user && props.user.automation_diagnostics_visible)
  );
}
