// Presentation anchors only. Neither snapshot is modified or merged.
export default function automationPendingRemovals(publishedNodes, draftNodes) {
  const draftPositions = new Map(draftNodes.map((node, index) => [node.id, index]));
  const seen = new Set();
  return publishedNodes.reduce((result, node, index) => {
    if (draftPositions.has(node.id) || seen.has(node.id)) return result;
    seen.add(node.id);
    const before = publishedNodes.slice(0, index).reverse().find(item => draftPositions.has(item.id));
    const after = publishedNodes.slice(index + 1).find(item => draftPositions.has(item.id));
    const reversed = before && after && draftPositions.get(before.id) >= draftPositions.get(after.id);
    const anchor = reversed ? null : (after || before);
    result.push({node, publishedStep: index + 1, anchorId: anchor ? anchor.id : null,
      side: after ? 'before' : 'after'});
    return result;
  }, []);
}
