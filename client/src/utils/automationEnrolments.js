export function enrolmentQueryParams(state) {
  const params = {
    view: state.view,
    page: state.page,
    page_size: state.pageSize,
  };
  if (state.appliedSearch) {
    params.search = state.appliedSearch;
  }
  if (state.nodeId) {
    params.node_id = state.nodeId;
  }
  if (state.nodePosition) {
    params.node_position = state.nodePosition;
  }
  return params;
}
