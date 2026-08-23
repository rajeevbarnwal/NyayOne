import { describe, expect, it } from 'vitest';
import { DraftWorkspaceService, workspaceIdFor } from './draftWorkspace';
import { InMemoryKvStore } from '../../../lib/kvStore';

const t = (n: number) => `2026-07-11T00:0${n}:00.000Z`;
const CASE = 'NYAY-CASE-2026-014';

function seed(svc: DraftWorkspaceService) {
  const ws = svc.create(CASE, 'Acme v. Sunrise');
  svc.addVersion(ws.workspaceId, { authorId: 'assoc:1', createdAt: t(1), changeNote: 'ai draft', body: 'A', aiGenerated: true, citations: [{ n: 1, title: 'CPC', ref: 'O7 R1', sourceVersion: 'as amended' }] });
  return ws.workspaceId;
}

describe('E06 draft workspace service (SAATHI-16 remediation)', () => {
  it('creates idempotently with a stable workspace id and current pointer', () => {
    const store = new InMemoryKvStore();
    const svc = new DraftWorkspaceService(store);
    const a = svc.create(CASE, 'X');
    const b = svc.create(CASE, 'X');
    expect(a.workspaceId).toBe(workspaceIdFor(CASE));
    expect(b.workspaceId).toBe(a.workspaceId);
    svc.setCurrent(a.workspaceId);
    expect(svc.getCurrent()).toBe(a.workspaceId);
  });

  it('appends versions and gates export until the latest version is approved', () => {
    const store = new InMemoryKvStore();
    const svc = new DraftWorkspaceService(store);
    const id = seed(svc);
    expect(svc.latestVersion(id)!.versionNo).toBe(1);
    expect(svc.canExport(id)).toBe(false);
    expect(svc.latestApprovedVersion(id)).toBeNull();

    svc.approve(id, svc.latestVersion(id)!.id, 'lawyer:rao', t(2));
    expect(svc.canExport(id)).toBe(true);
    expect(svc.latestApprovedVersion(id)!.versionNo).toBe(1);

    // Post-approval edit creates a new unapproved version → export re-blocked.
    svc.addVersion(id, { authorId: 'lawyer:rao', createdAt: t(3), changeNote: 'edit', body: 'B', aiGenerated: false });
    expect(svc.canExport(id)).toBe(false);
    // Latest APPROVED remains v1 (approval did not transfer to the new version).
    expect(svc.latestApprovedVersion(id)!.versionNo).toBe(1);
    expect(svc.latestVersion(id)!.versionNo).toBe(2);
  });

  it('restores workspace state across a simulated reload (new service, same store)', () => {
    const store = new InMemoryKvStore();
    const svc1 = new DraftWorkspaceService(store);
    const id = seed(svc1);
    svc1.approve(id, svc1.latestVersion(id)!.id, 'lawyer:rao', t(2));
    // Simulate reload: a fresh service instance backed by the same persisted store.
    const svc2 = new DraftWorkspaceService(store);
    expect(svc2.get(id)!.versions).toHaveLength(1);
    expect(svc2.latestApprovedVersion(id)!.versionNo).toBe(1);
    expect(svc2.canExport(id)).toBe(true);
  });
});
