# Automation loops and nested preview

Backward and cross-branch targets use the existing stable node IDs. Publishing
still rejects missing targets, direct self-targets and duplicate IDs, but no
longer requires a static guaranteed-wait path through every cycle.

Each enrolment persists `visited_node_ids` across scheduler ticks. A successful
node adds its ID; reaching an already visited node holds the enrolment before
executing that action again. This also catches inner loops which never return
to the enrolment's initial node. Ordinary retries do not add visits.

A duration wait's start and completion are one visit. Completion clears visits
only when its wake time has arrived and at least five minutes have actually
elapsed since starting. Manual skip and an already-past wake time without a
genuine delay do not reset the guard. Duration-node validation is unchanged.
The existing transition budget remains a secondary bound.

Pause/resume, publication of retained nodes, and moving a node with the follow
choice preserve visits. Explicit fresh-destination migration clears visits;
new enrolments start with an empty history. Existing enrolments without the
field begin tracking on their next successful step. There is no reconstruction
of previous visits. A held loop requires correcting the path or an explicit
fresh migration; simply resuming cannot bypass the guard.

The same automation-owned email is handed off at most once per rolling 24-hour
window per account/contact, including different nodes and re-enrolments. A
confirmed recent send is skipped and execution advances. The history explains
the skip. A short reservation under the existing automation lock serializes
competing enrolments; external delivery happens after releasing that lock.
Step-run history stores the reservation and handoff result. A concurrent pending
send retries with existing backoff; an uncertain outcome holds rather than
blindly resending. Definite local Drop All Mail rejection keeps existing retries.
Test-email sends are outside this execution throttle.

This is not a provider exactly-once delivery guarantee. A crash can leave a
pending reservation, and a network timeout can leave an uncertain outcome.
Existing stale-claim recovery does not erase reservations. Review provider
delivery before recovery; no automatic uncertain-delivery repair is provided.
Reservations/sends older than 24 hours no longer block a new attempt. Preserving
step-run history within that window is part of the throttle's storage contract.

Nested preview widths are calculated from leaves upward (340px per leaf plus
32px between subtrees). Both children reserve their complete descendant width;
ancestors expand without reordering the draft. Wide trees start centred on the
root and scroll horizontally, preserving the user's offset during editing.
Shared nodes and backward jumps retain bounded reference rendering, rather than
recursively expanding the same node. This layout adds no execution semantics.
