import assert from 'node:assert/strict';
import test from 'node:test';
import { unconnectedOverview } from '../src/lib/soc-overview.ts';

test('une base accessible ne devient pas une preuve de raccordement des agents', () => {
  const overview = unconnectedOverview('2026-10-10T16:00:00Z');
  assert.equal(overview.databaseConnected, true);
  assert.equal(overview.pipelineConnected, false);
  assert.deepEqual(overview.agents, []);
  assert.deepEqual(overview.reviews, []);
  assert.deepEqual(overview.incidents, []);
  assert.deepEqual(overview.activity, []);
  assert.equal(overview.blockedActions, null);
  assert.equal(overview.completedTests, null);
});
