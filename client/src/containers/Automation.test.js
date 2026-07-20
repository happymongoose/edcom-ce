import _ from 'underscore';

import {
  automationEnrolmentAction,
  automationHistoryLog,
  canReEnrolAutomation,
  displayAutomationEnrolments,
} from './Automation';

describe('automation enrolment display helpers', () => {
  it('only allows rerun UI when published reentry is multiple', () => {
    expect(canReEnrolAutomation({published: {reentry: 'multiple'}})).toBe(true);
    expect(canReEnrolAutomation({published: {reentry: 'once'}})).toBe(false);
    expect(canReEnrolAutomation({reentry: 'multiple'})).toBe(false);
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

  it('does not show run controls for held or paused enrolments', () => {
    _.each(['held', 'paused_ready', 'paused_waiting'], status => {
      const action = automationEnrolmentAction(
        {status: status, wake_at: '2026-07-20T10:05:00Z'},
        {published: {reentry: 'multiple'}},
        '2026-07-20T10:06:00Z'
      );
      expect(action.type).toBe('none');
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
});
