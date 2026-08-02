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
import { enrolmentQueryParams } from '../utils/automationEnrolments';
import { canViewAutomationDiagnostics } from '../utils/automationDiagnostics';

describe('automation enrolment display helpers', () => {
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
