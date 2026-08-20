import _ from 'underscore';

import {
  automationEnrolmentAction,
  filterAutomationHistoryContacts,
  automationHistoryContacts,
  automationHistoryLogForEnrolment,
  automationHistoryLog,
  automationEnrolmentCounts,
  automationImpersonatedHref,
  automationNodeContactCount,
  automationNodeContactFilterId,
  automationNodeContactFilterParam,
  paginateAutomationHistoryContacts,
  sortAutomationHistoryContacts,
  canReEnrolAutomation,
  displayAutomationEnrolments,
  entryPayload,
  entryTriggers,
} from './Automation';
import {
  appendAutomationNode,
  automationNodeSummary,
  automationNodeTargetOptions,
  insertAutomationNodeAfter,
  moveAutomationNode,
} from './AutomationWorkflowEditor';
import { enrolmentQueryParams } from '../utils/automationEnrolments';
import { canViewAutomationDiagnostics } from '../utils/automationDiagnostics';

describe('automation enrolment display helpers', () => {
  it('appends workflow nodes with a new stable id', () => {
    const nodes = [
      {id: 'node-1', type: 'add_tag', label: 'Existing node'},
    ];

    const updated = appendAutomationNode(nodes, 'wait_duration', {generateId: () => 'new-node'});

    expect(_.pluck(updated, 'id')).toEqual(['node-1', 'new-node']);
    expect(updated[1].duration).toEqual({days: 0, hours: 0, minutes: 5});
    expect(nodes).toHaveLength(1);
  });

  it('creates clicked-email condition nodes as any-link by default', () => {
    const updated = appendAutomationNode([], 'if_clicked_email', {
      generateId: () => 'clicked-node',
      emails: [{id: 'email-1'}],
    });

    expect(updated[0].click_match).toBe('any');
    expect(updated[0].link_url).toBe('');
    expect(updated[0].automation_email_id).toBe('email-1');
  });

  it('inserts workflow nodes after a step without rewriting branch targets', () => {
    const nodes = [
      {id: 'condition', type: 'if_has_tag', label: 'Check tag', yes_node_id: 'target', no_node_id: 'exit'},
      {id: 'target', type: 'add_tag', label: 'Target tag'},
      {id: 'exit', type: 'exit', label: 'Exit'},
    ];

    const updated = insertAutomationNodeAfter(nodes, 0, 'wait_duration', {generateId: () => 'inserted'});

    expect(_.pluck(updated, 'id')).toEqual(['condition', 'inserted', 'target', 'exit']);
    expect(updated[0].yes_node_id).toBe('target');
    expect(updated[0].no_node_id).toBe('exit');
  });

  it('updates target dropdown step labels after insertion while preserving target ids', () => {
    const nodes = [
      {id: 'condition', type: 'if_has_tag', label: 'Check tag', yes_node_id: 'target', no_node_id: 'exit'},
      {id: 'target', type: 'add_tag', label: 'Target tag'},
      {id: 'exit', type: 'exit', label: 'Exit'},
    ];
    const updated = insertAutomationNodeAfter(nodes, 0, 'wait_duration', {generateId: () => 'inserted'});

    const options = automationNodeTargetOptions(updated, updated[0]);
    const target = _.findWhere(options, {id: 'target'});

    expect(target.id).toBe('target');
    expect(target.name).toBe('Step 3 - Target tag (Add tag)');
  });

  it('moves workflow nodes up and down while preserving node ids', () => {
    const nodes = [
      {id: 'first', type: 'add_tag', label: 'First'},
      {id: 'second', type: 'wait_duration', label: 'Second'},
      {id: 'third', type: 'exit', label: 'Third'},
    ];

    expect(_.pluck(moveAutomationNode(nodes, 1, -1), 'id')).toEqual(['second', 'first', 'third']);
    expect(_.pluck(moveAutomationNode(nodes, 1, 1), 'id')).toEqual(['first', 'third', 'second']);
    expect(_.pluck(nodes, 'id')).toEqual(['first', 'second', 'third']);
  });

  it('does not move the first node up or the last node down', () => {
    const nodes = [
      {id: 'first', type: 'add_tag', label: 'First'},
      {id: 'second', type: 'exit', label: 'Second'},
    ];

    expect(_.pluck(moveAutomationNode(nodes, 0, -1), 'id')).toEqual(['first', 'second']);
    expect(_.pluck(moveAutomationNode(nodes, 1, 1), 'id')).toEqual(['first', 'second']);
  });

  it('moves workflow nodes without rewriting branch or go-to target ids', () => {
    const nodes = [
      {id: 'condition', type: 'if_has_tag', label: 'Check tag', yes_node_id: 'target', no_node_id: 'exit'},
      {id: 'go', type: 'go_to', label: 'Go forward', target_node_id: 'target'},
      {id: 'target', type: 'add_tag', label: 'Target tag'},
      {id: 'exit', type: 'exit', label: 'Exit'},
    ];

    const updated = moveAutomationNode(nodes, 2, -1);

    expect(_.pluck(updated, 'id')).toEqual(['condition', 'target', 'go', 'exit']);
    expect(updated[0].yes_node_id).toBe('target');
    expect(updated[0].no_node_id).toBe('exit');
    expect(updated[2].target_node_id).toBe('target');
  });

  it('moves workflow nodes without rewriting email list tag or wait configuration', () => {
    const nodes = [
      {id: 'send', type: 'send_email', label: 'Send', automation_email_id: 'email-1'},
      {id: 'list', type: 'add_to_list', label: 'List', list_id: 'list-1'},
      {id: 'tag', type: 'add_tag', label: 'Tag', draft_tag: 'vip'},
      {id: 'wait', type: 'wait_duration', label: 'Wait', duration: {days: 1, hours: 2, minutes: 3}},
    ];

    const updated = moveAutomationNode(nodes, 3, -1);

    expect(_.pluck(updated, 'id')).toEqual(['send', 'list', 'wait', 'tag']);
    expect(updated[0].automation_email_id).toBe('email-1');
    expect(updated[1].list_id).toBe('list-1');
    expect(updated[2].duration).toEqual({days: 1, hours: 2, minutes: 3});
    expect(updated[3].draft_tag).toBe('vip');
  });

  it('updates target dropdown step labels after moving nodes', () => {
    const nodes = [
      {id: 'condition', type: 'if_has_tag', label: 'Check tag', yes_node_id: 'target', no_node_id: 'exit'},
      {id: 'wait', type: 'wait_duration', label: 'Wait'},
      {id: 'target', type: 'add_tag', label: 'Target tag'},
      {id: 'exit', type: 'exit', label: 'Exit'},
    ];

    const updated = moveAutomationNode(nodes, 2, -1);
    const options = automationNodeTargetOptions(updated, updated[0]);
    const target = _.findWhere(options, {id: 'target'});

    expect(target.id).toBe('target');
    expect(target.name).toBe('Step 2 - Target tag (Add tag)');
  });

  it('summarizes major workflow node types', () => {
    const emails = [{id: 'email-1', name: 'Welcome', subject: 'Hello', type: 'raw'}];
    const lists = [{id: 'list-1', name: 'Customers', count: 42}];
    const nodes = [
      {id: 'send', type: 'send_email', automation_email_id: 'email-1'},
      {id: 'add-tag', type: 'add_tag', draft_tag: 'vip'},
      {id: 'remove-tag', type: 'remove_tag', draft_tag: 'old'},
      {id: 'add-list', type: 'add_to_list', list_id: 'list-1'},
      {id: 'remove-list', type: 'remove_from_list', list_id: 'list-1'},
      {id: 'wait', type: 'wait_duration', duration: {days: 1, hours: 2, minutes: 3}},
      {id: 'exit', type: 'exit'},
    ];
    const options = {nodes: nodes, emails: emails, lists: lists};

    expect(automationNodeSummary(nodes[0], options)).toBe('Send email: Welcome - Hello (HTML)');
    expect(automationNodeSummary(nodes[1], options)).toBe('Add tag: vip');
    expect(automationNodeSummary(nodes[2], options)).toBe('Remove tag: old');
    expect(automationNodeSummary(nodes[3], options)).toBe('Add to list: Customers (42 contacts)');
    expect(automationNodeSummary(nodes[4], options)).toBe('Remove from list: Customers (42 contacts)');
    expect(automationNodeSummary(nodes[5], options)).toBe('Wait: 1 day 2 hours 3 minutes');
    expect(automationNodeSummary(nodes[6], options)).toBe('Exit automation');
  });

  it('summarizes missing workflow references clearly', () => {
    expect(automationNodeSummary({id: 'send', type: 'send_email'}, {})).toBe('No email selected');
    expect(automationNodeSummary({id: 'send', type: 'send_email', automation_email_id: 'missing'}, {})).toBe('Send email: Selected email not found');
    expect(automationNodeSummary({id: 'list', type: 'add_to_list'}, {})).toBe('No list selected');
    expect(automationNodeSummary({id: 'list', type: 'add_to_list', list_id: 'missing'}, {})).toBe('Add to list: Selected list not found');
    expect(automationNodeSummary({id: 'wait', type: 'wait_duration', duration: {}}, {})).toBe('Wait: Wait duration incomplete');
    expect(automationNodeSummary({id: 'go', type: 'go_to'}, {nodes: []})).toBe('Go to: Target missing');
  });

  it('summarizes condition targets and updates target step labels after reorder', () => {
    const nodes = [
      {id: 'condition', type: 'if_has_tag', draft_tag: 'vip', yes_node_id: 'yes', no_node_id: 'no'},
      {id: 'wait', type: 'wait_duration', label: 'Wait'},
      {id: 'yes', type: 'add_tag', label: 'Yes target'},
      {id: 'no', type: 'exit', label: 'No target'},
    ];
    const moved = moveAutomationNode(nodes, 2, -1);

    expect(automationNodeSummary(moved[0], {nodes: moved})).toBe(
      'If has tag: vip | Yes -> Step 2 - Yes target (Add tag) | No -> Step 4 - No target (Exit)'
    );
  });

  it('summarizes email engagement conditions', () => {
    const emails = [{id: 'email-1', name: 'Welcome', subject: 'Hello', type: 'beefree'}];
    const nodes = [
      {id: 'opened', type: 'if_opened_email', automation_email_id: 'email-1', yes_node_id: 'yes', no_node_id: 'no'},
      {id: 'clicked', type: 'if_clicked_email', automation_email_id: 'email-1', yes_node_id: 'yes', no_node_id: 'no'},
      {id: 'yes', type: 'add_tag', label: 'Yes'},
      {id: 'no', type: 'exit', label: 'No'},
    ];

    expect(automationNodeSummary(nodes[0], {nodes: nodes, emails: emails})).toBe(
      'If opened: Welcome - Hello (BeeFree) | Yes -> Step 3 - Yes (Add tag) | No -> Step 4 - No (Exit)'
    );
    expect(automationNodeSummary(nodes[1], {nodes: nodes, emails: emails})).toBe(
      'If clicked any link: Welcome - Hello (BeeFree) | Yes -> Step 3 - Yes (Add tag) | No -> Step 4 - No (Exit)'
    );
  });

  it('summarizes specific-url clicked email conditions', () => {
    const emails = [{id: 'email-1', name: 'Welcome', subject: 'Hello', type: 'raw'}];
    const nodes = [
      {
        id: 'clicked',
        type: 'if_clicked_email',
        automation_email_id: 'email-1',
        click_match: 'url',
        link_url: 'https://example.com/offer',
        yes_node_id: 'yes',
        no_node_id: 'no',
      },
      {id: 'yes', type: 'add_tag', label: 'Yes'},
      {id: 'no', type: 'exit', label: 'No'},
    ];

    expect(automationNodeSummary(nodes[0], {nodes: nodes, emails: emails})).toBe(
      'If clicked specific URL: https://example.com/offer: Welcome - Hello (HTML) | Yes -> Step 2 - Yes (Add tag) | No -> Step 3 - No (Exit)'
    );
  });

  it('shows automation diagnostics only for admin, impersonation or enabled accounts', () => {
    expect(canViewAutomationDiagnostics({user: {admin: true}})).toBe(true);
    expect(canViewAutomationDiagnostics({loggedInImpersonate: true, user: {}})).toBe(true);
    expect(canViewAutomationDiagnostics({user: {automation_diagnostics_visible: true}})).toBe(true);
    expect(canViewAutomationDiagnostics({user: {automation_diagnostics_visible: false}})).toBe(false);
    expect(canViewAutomationDiagnostics({user: {}})).toBe(false);
  });

  it('only allows rerun UI when published reentry is multiple', () => {
    expect(canReEnrolAutomation({published: {reentry: 'multiple'}})).toBe(true);
    expect(canReEnrolAutomation({published: {reentry: 'once'}})).toBe(false);
    expect(canReEnrolAutomation({reentry: 'multiple'})).toBe(true);
  });

  it('loads old single entry triggers as one trigger row', () => {
    expect(entryTriggers({type: 'tag_added', tag: 'vip'})).toEqual([
      {type: 'tag_added', tag: 'vip'},
    ]);
  });

  it('saves one entry trigger as the existing single shape', () => {
    expect(entryPayload({type: 'multi', triggers: [{type: 'tag_removed', tag: 'old'}]})).toEqual({
      type: 'tag_removed',
      tag: 'old',
    });
  });

  it('saves multiple entry triggers as multi shape', () => {
    expect(entryPayload({
      type: 'multi',
      triggers: [
        {type: 'manual'},
        {type: 'list_left', list_id: 'list-1'},
      ],
    })).toEqual({
      type: 'multi',
      triggers: [
        {type: 'manual'},
        {type: 'list_left', list_id: 'list-1'},
      ],
    });
  });

  it('omits empty optional enrolment query parameters', () => {
    expect(enrolmentQueryParams({
      view: 'all',
      page: 1,
      pageSize: 50,
      appliedSearch: '',
      nodeId: '',
      nodePosition: '',
    })).toEqual({
      view: 'all',
      page: 1,
      page_size: 50,
    });
  });

  it('counts active and ever-enrolled automation contacts', () => {
    const counts = automationEnrolmentCounts([
      {id: 'ready-1', contact_id: 1, contact_email: 'one@example.com', status: 'ready'},
      {id: 'waiting-1', contact_id: 2, contact_email: 'two@example.com', status: 'waiting'},
      {id: 'completed-1', contact_id: 3, contact_email: 'three@example.com', status: 'completed'},
      {id: 'completed-2', contact_id: 1, contact_email: 'one@example.com', status: 'completed'},
      {id: 'failed-1', contact_id: 4, contact_email: 'four@example.com', status: 'failed'},
    ]);

    expect(counts).toEqual({
      active: 2,
      enrolled: 4,
    });
  });

  it('preserves impersonation when opening automation enrolment pages in new tabs', () => {
    expect(automationImpersonatedHref('/automations/abc/enrolments?view=active', 'customer-1')).toBe(
      '/automations/abc/enrolments?view=active&impersonate=customer-1'
    );
    expect(automationImpersonatedHref('/automations/abc/enrolments', 'customer 1')).toBe(
      '/automations/abc/enrolments?impersonate=customer%201'
    );
    expect(automationImpersonatedHref('/automations/abc/enrolments', '')).toBe('/automations/abc/enrolments');
  });

  it('maps draft step contact counts to matching published step ids', () => {
    const draftNodes = [
      {id: 'draft-send', label: 'Send email'},
      {id: 'draft-tag', label: 'Add tag'},
    ];
    const publishedNodes = [
      {id: 'published-send', label: 'Send email'},
      {id: 'published-tag', label: 'Add tag'},
    ];
    const summary = {
      nodes: {
        'published-send': 1,
        'draft-tag': 2,
        'published-tag': 3,
      },
    };

    expect(automationNodeContactCount(draftNodes[0], draftNodes, publishedNodes, summary)).toBe(1);
    expect(automationNodeContactCount(draftNodes[1], draftNodes, publishedNodes, summary)).toBe(5);
    expect(automationNodeContactFilterId(draftNodes[0], draftNodes, publishedNodes)).toBe('published-send');
    expect(automationNodeContactFilterParam(draftNodes[0], draftNodes, publishedNodes, summary)).toEqual({
      key: 'node_id',
      value: 'published-send',
    });
  });

  it('prefers step-position counts for older active revisions', () => {
    const draftNodes = [
      {id: 'draft-send', label: 'Send email'},
      {id: 'draft-tag', label: 'Add tag'},
    ];
    const summary = {
      nodes: {
        'old-wait-node': 1,
      },
      node_positions: {
        '2': 1,
      },
    };

    expect(automationNodeContactCount(draftNodes[1], draftNodes, [], summary)).toBe(1);
    expect(automationNodeContactFilterParam(draftNodes[1], draftNodes, [], summary)).toEqual({
      key: 'node_position',
      value: '2',
    });
  });

  it('collapses sessions by contact and prefers the latest ready session', () => {
    const rows = displayAutomationEnrolments([
      {
        id: 'old-exited',
        contact_id: 123,
        contact_email: 'contact@example.com',
        status: 'exited',
        current_node_id: 'exit',
        created: '2026-07-20T10:00:00Z',
      },
      {
        id: 'new-ready',
        contact_id: 123,
        contact_email: 'contact@example.com',
        status: 'ready',
        current_node_id: 'first-node',
        created: '2026-07-20T11:00:00Z',
      },
    ]);

    expect(rows).toHaveLength(1);
    expect(rows[0].id).toBe('new-ready');
    expect(rows[0].current_node_id).toBe('first-node');
  });

  it('collapses sessions by contact and uses latest history when no session is ready', () => {
    const rows = displayAutomationEnrolments([
      {
        id: 'first-exit',
        contact_id: 123,
        contact_email: 'contact@example.com',
        status: 'exited',
        created: '2026-07-20T10:00:00Z',
      },
      {
        id: 'latest-exit',
        contact_id: 123,
        contact_email: 'contact@example.com',
        status: 'exited',
        created: '2026-07-20T11:00:00Z',
      },
    ]);

    expect(rows).toHaveLength(1);
    expect(rows[0].id).toBe('latest-exit');
  });

  it('formats automation history as copy-friendly text', () => {
    const log = automationHistoryLog({
      events: [
        {
          type: 'enrolment',
          created: '2026-07-20T10:00:00Z',
          contact_email: 'contact@example.com',
          enrolment_id: 'enrolment-1',
          status: 'paused_waiting',
          source: 'manual',
          current_node_id: 'node_add_tag_1',
          paused_at: '2026-07-20T10:02:00Z',
          remaining_seconds: 180,
          published_revision: 3,
        },
        {
          type: 'step_run',
          created: '2026-07-20T10:01:00Z',
          contact_email: 'contact@example.com',
          enrolment_id: 'enrolment-1',
          node_id: 'node_add_tag_1',
          node_type: 'add_tag',
          node_label: 'Add history tag',
          tag: 'history-tag',
          status: 'succeeded',
          published_revision: 3,
        },
      ],
    });

    expect(log).toContain('contact@example.com | enrolment enrolment-1 | enrolled');
    expect(log).toContain('status=paused_waiting');
    expect(log).toContain('paused_at=2026-07-20T10:02:00Z');
    expect(log).toContain('remaining_seconds=180');
    expect(log).toContain('step add_tag node_add_tag_1 | "Add history tag" | tag=history-tag');
    expect(log).toContain('revision=3');
  });

  it('can format automation history newest first for the all-history log', () => {
    const log = automationHistoryLog({
      events: [
        {
          type: 'enrolment',
          created: '2026-07-20T10:00:00Z',
          contact_email: 'contact@example.com',
          enrolment_id: 'old-pass',
          status: 'completed',
          published_revision: 1,
        },
        {
          type: 'step_run',
          created: '2026-07-20T11:00:00Z',
          contact_email: 'contact@example.com',
          enrolment_id: 'new-pass',
          node_id: 'node_send_1',
          node_type: 'send_email',
          status: 'succeeded',
          published_revision: 2,
        },
      ],
    }, {newestFirst: true});

    expect(log.indexOf('enrolment new-pass')).toBeLessThan(log.indexOf('enrolment old-pass'));
  });

  it('shows waiting and continue actions for waiting enrolments', () => {
    const waiting = automationEnrolmentAction(
      {
        status: 'waiting',
        wake_at: '2026-07-20T10:05:00Z',
      },
      {published: {reentry: 'multiple'}},
      '2026-07-20T10:00:00Z'
    );
    expect(waiting.type).toBe('skip_wait');
    expect(waiting.disabled).toBe(false);
    expect(waiting.label).toBe('Move to next node');
    expect(waiting.waitLabel).toContain('Waiting until');

    const elapsed = automationEnrolmentAction(
      {
        status: 'waiting',
        wake_at: '2026-07-20T10:05:00Z',
      },
      {published: {reentry: 'multiple'}},
      '2026-07-20T10:06:00Z'
    );
    expect(elapsed.type).toBe('continue_wait');
    expect(elapsed.label).toBe('Continue test');
  });

  it('shows rerun for terminal enrolments when reentry is multiple', () => {
    _.each(['completed', 'exited', 'cancelled'], status => {
      const action = automationEnrolmentAction(
        {status: status},
        {published: {reentry: 'multiple'}}
      );
      expect(action.type).toBe('reenrol');
      expect(action.label).toBe('Run automation again');
      expect(action.disabled).toBe(false);
    });

    expect(automationEnrolmentAction(
      {status: 'completed'},
      {reentry: 'multiple'}
    ).type).toBe('reenrol');
  });

  it('does not show rerun for non-terminal enrolments when reentry is multiple', () => {
    _.each(['held', 'paused_ready', 'paused_waiting', 'running', 'failed'], status => {
      const action = automationEnrolmentAction(
        {status: status, wake_at: '2026-07-20T10:05:00Z'},
        {published: {reentry: 'multiple'}},
        '2026-07-20T10:06:00Z'
      );
      expect(action.type).toBe('none');
    });

    expect(automationEnrolmentAction(
      {status: 'ready'},
      {published: {reentry: 'multiple'}}
    ).type).toBe('run_next');
    expect(automationEnrolmentAction(
      {status: 'waiting', wake_at: '2026-07-20T10:05:00Z'},
      {published: {reentry: 'multiple'}},
      '2026-07-20T10:00:00Z'
    ).type).toBe('skip_wait');
  });

  it('never shows rerun after terminal enrolments when reentry is once', () => {
    _.each(['completed', 'exited', 'cancelled'], status => {
      const action = automationEnrolmentAction(
        {status: status},
        {published: {reentry: 'once'}}
      );
      expect(action.type).toBe('none');
      expect(action.disabled).toBe(true);
    });
  });

  it('includes wait metadata in copy-friendly history text', () => {
    const log = automationHistoryLog({
      events: [
        {
          type: 'step_run',
          created: '2026-07-20T10:00:00Z',
          contact_email: 'contact@example.com',
          enrolment_id: 'enrolment-1',
          node_id: 'node_wait_1',
          node_type: 'wait_duration',
          node_label: 'Wait',
          action: 'wait_start',
          wake_at: '2026-07-20T10:05:00Z',
          skipped: true,
          status: 'waiting',
          published_revision: 3,
        },
      ],
    });

    expect(log).toContain('action=wait_start');
    expect(log).toContain('wake_at=2026-07-20T10:05:00Z');
    expect(log).toContain('skipped=true');
    expect(log).toContain('status=waiting');
  });

  it('includes branch and go to metadata in copy-friendly history text', () => {
    const log = automationHistoryLog({
      events: [
        {
          type: 'step_run',
          created: '2026-07-20T10:00:00Z',
          contact_email: 'contact@example.com',
          enrolment_id: 'enrolment-1',
          node_id: 'node_condition_1',
          node_type: 'if_has_tag',
          node_label: 'Check VIP tag',
          action: 'branch',
          tag: 'vip',
          result: true,
          branch: 'yes',
          target_node_id: 'node_yes_1',
          status: 'succeeded',
          published_revision: 3,
        },
        {
          type: 'step_run',
          created: '2026-07-20T10:01:00Z',
          contact_email: 'contact@example.com',
          enrolment_id: 'enrolment-1',
          node_id: 'node_go_to_1',
          node_type: 'go_to',
          node_label: 'Go to shared step',
          action: 'go_to',
          target_node_id: 'node_shared_1',
          status: 'succeeded',
          published_revision: 3,
        },
      ],
    });

    expect(log).toContain('action=branch');
    expect(log).toContain('tag=vip');
    expect(log).toContain('result=true');
    expect(log).toContain('branch=yes');
    expect(log).toContain('target=node_yes_1');
    expect(log).toContain('action=go_to');
    expect(log).toContain('target=node_shared_1');
  });

  it('includes send email metadata in copy-friendly history text', () => {
    const log = automationHistoryLog({
      events: [
        {
          type: 'step_run',
          created: '2026-07-20T10:00:00Z',
          contact_email: 'contact@example.com',
          enrolment_id: 'enrolment-1',
          node_id: 'node_send_1',
          node_type: 'send_email',
          node_label: 'Send welcome',
          action: 'send_email',
          automation_email_id: 'email-1',
          automation_email_name: 'Welcome email',
          subject: 'Welcome',
          recipient_email: 'contact@example.com',
          route_id: 'route-1',
          sent: true,
          status: 'succeeded',
          published_revision: 4,
        },
      ],
    });

    expect(log).toContain('action=send_email');
    expect(log).toContain('automation_email=email-1');
    expect(log).toContain('email_name="Welcome email"');
    expect(log).toContain('subject="Welcome"');
    expect(log).toContain('recipient=contact@example.com');
    expect(log).toContain('route=route-1');
    expect(log).toContain('sent=true');
  });

  it('includes engagement events in copy-friendly history text', () => {
    const log = automationHistoryLog({
      events: [
        {
          type: 'engagement',
          event_type: 'open',
          created: '2026-07-24T21:12:00Z',
          contact_email: 'sarah@example.com',
          enrolment_id: 'enrolment-1',
          automation_email_id: 'email-1',
          automation_email_name: 'Welcome email',
          subject: 'Welcome',
          send_step_run_id: 'step-run-1',
          inferred: true,
          inferred_from_event_type: 'click',
        },
        {
          type: 'engagement',
          event_type: 'click',
          created: '2026-07-24T21:13:00Z',
          contact_email: 'sarah@example.com',
          enrolment_id: 'enrolment-1',
          automation_email_id: 'email-1',
          automation_email_name: 'Welcome email',
          subject: 'Welcome',
          send_step_run_id: 'step-run-1',
          link_url: 'https://example.com/offer',
          link_index: 2,
        },
      ],
    });

    expect(log).toContain('sarah@example.com | enrolment enrolment-1 | engagement open');
    expect(log).toContain('email_name="Welcome email"');
    expect(log).toContain('send_step=step-run-1');
    expect(log).toContain('inferred=true');
    expect(log).toContain('inferred_from=click');
    expect(log).toContain('engagement click');
    expect(log).toContain('link=https://example.com/offer');
    expect(log).toContain('link_index=2');
  });

  it('groups debug history by contact email and sorts contacts by latest pass first', () => {
    const contacts = automationHistoryContacts({
      enrolments: [
        {
          id: 'older-pass',
          contact_email: 'z-contact@example.com',
          created: '2026-07-20T10:00:00Z',
        },
        {
          id: 'newer-pass',
          contact_email: 'z-contact@example.com',
          created: '2026-07-20T11:00:00Z',
        },
        {
          id: 'other-pass',
          contact_email: 'a-other@example.com',
          created: '2026-07-20T12:00:00Z',
        },
      ],
    });

    expect(contacts).toHaveLength(2);
    expect(contacts[0].email).toBe('a-other@example.com');
    expect(contacts[1].email).toBe('z-contact@example.com');
    expect(_.pluck(contacts[1].enrolments, 'id')).toEqual(['newer-pass', 'older-pass']);
  });

  it('filters debug history contacts by email address', () => {
    const contacts = [
      {email: 'sarah@example.com'},
      {email: 'simon@example.com'},
      {email: 'admin@test.com'},
    ];

    expect(_.pluck(filterAutomationHistoryContacts(contacts, 'SIM'), 'email')).toEqual(['simon@example.com']);
    expect(_.pluck(filterAutomationHistoryContacts(contacts, 'example.com'), 'email')).toEqual(['sarah@example.com', 'simon@example.com']);
    expect(filterAutomationHistoryContacts(contacts, '')).toEqual(contacts);
  });

  it('paginates debug history contacts in groups of 50', () => {
    const contacts = _.map(_.range(0, 121), index => ({email: 'contact-' + index + '@example.com'}));

    const first = paginateAutomationHistoryContacts(contacts, 1, 50);
    expect(first.total).toBe(121);
    expect(first.totalPages).toBe(3);
    expect(first.page).toBe(1);
    expect(first.contacts).toHaveLength(50);
    expect(first.contacts[0].email).toBe('contact-0@example.com');

    const third = paginateAutomationHistoryContacts(contacts, 3, 50);
    expect(third.page).toBe(3);
    expect(third.contacts).toHaveLength(21);
    expect(third.contacts[0].email).toBe('contact-100@example.com');

    const clamped = paginateAutomationHistoryContacts(contacts, 99, 50);
    expect(clamped.page).toBe(3);
  });

  it('sorts debug history contacts by recent pass and email in both directions', () => {
    const contacts = [
      {email: 'sarah@example.com', latest_created: '2026-07-20T10:00:00Z'},
      {email: 'admin@example.com', latest_created: '2026-07-20T12:00:00Z'},
      {email: 'zoe@example.com', latest_created: '2026-07-20T11:00:00Z'},
    ];

    expect(_.pluck(sortAutomationHistoryContacts(contacts, 'recent_desc'), 'email')).toEqual([
      'admin@example.com',
      'zoe@example.com',
      'sarah@example.com',
    ]);
    expect(_.pluck(sortAutomationHistoryContacts(contacts, 'recent_asc'), 'email')).toEqual([
      'sarah@example.com',
      'zoe@example.com',
      'admin@example.com',
    ]);
    expect(_.pluck(sortAutomationHistoryContacts(contacts, 'email_asc'), 'email')).toEqual([
      'admin@example.com',
      'sarah@example.com',
      'zoe@example.com',
    ]);
    expect(_.pluck(sortAutomationHistoryContacts(contacts, 'email_desc'), 'email')).toEqual([
      'zoe@example.com',
      'sarah@example.com',
      'admin@example.com',
    ]);
  });

  it('formats copy-friendly history text for one pass only', () => {
    const log = automationHistoryLogForEnrolment({
      enrolments: [
        {
          id: 'pass-1',
          contact_email: 'contact@example.com',
        },
        {
          id: 'pass-2',
          contact_email: 'contact@example.com',
        },
      ],
      events: [
        {
          type: 'enrolment',
          created: '2026-07-20T10:00:00Z',
          contact_email: 'contact@example.com',
          enrolment_id: 'pass-1',
          status: 'completed',
          published_revision: 3,
        },
        {
          type: 'step_run',
          created: '2026-07-20T11:00:00Z',
          contact_email: 'contact@example.com',
          enrolment_id: 'pass-2',
          node_id: 'node_add_tag_2',
          node_type: 'add_tag',
          node_label: 'Add tag',
          tag: 'second-pass',
          status: 'succeeded',
          published_revision: 4,
        },
      ],
    }, 'pass-2');

    expect(log).toContain('enrolment pass-2');
    expect(log).toContain('step add_tag node_add_tag_2');
    expect(log).toContain('tag=second-pass');
    expect(log).toContain('revision=4');
    expect(log).not.toContain('pass-1');
  });
});
