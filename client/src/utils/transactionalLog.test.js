import { serializeDatetimeFilterValue } from './transactionalLog';

describe('serializeDatetimeFilterValue', () => {
  it('serializes a browser datetime-local value to an ISO timestamp', () => {
    const value = '2026-07-08T21:33';
    expect(serializeDatetimeFilterValue(value)).toBe(new Date(value).toISOString());
  });

  it('returns an empty string for blank input', () => {
    expect(serializeDatetimeFilterValue('')).toBe('');
  });
});
