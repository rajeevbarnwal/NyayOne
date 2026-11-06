import {it,expect} from 'vitest';
import {execFileSync} from 'node:child_process';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {approveException,finalizeEnforcement} from './nyay66-enforcement.mjs';
import {withoutS33ProposalsForTest,withoutS33PolicyBytesForTest} from './nyay66-s33-exceptions.test-fixture.mjs';
import {s33RecoveryOld,s33RecoveryNew,s33RecoveryHashes} from './nyay66-s33-recovery-reapproval.test-fixture.mjs';
const root=fileURLToPath(new URL('../../../',import.meta.url));
const bytes=execFileSync('git',['show','f1110f4b501f8604696db0bca20b6f5320dcc00b:frontend/scripts/nyay66-policy.json'],{cwd:root,encoding:'utf8'}),baseline=JSON.parse(bytes);
const record=e=>JSON.stringify(e,null,2).replace(/^/gm,'    ');
const indices=s33RecoveryOld.map(e=>baseline.exceptions.findIndex(x=>JSON.stringify(x)===JSON.stringify(e)));
const candidate=()=>{const p=structuredClone(baseline);indices.forEach((n,i)=>p.exceptions[n]=structuredClone(s33RecoveryNew[i]));return p;};
const check=p=>expect(withoutS33ProposalsForTest(p.exceptions)).toEqual(withoutS33ProposalsForTest(baseline.exceptions));
it('accepts only the two exact recovery replacements, preserving 296 other records and raw bytes',()=>{
 expect(indices.every(n=>n>=0)).toBe(true);expect(new Set(indices).size).toBe(2);expect(baseline.exceptions).toHaveLength(298);
 expect(s33RecoveryNew.map(e=>approveException(e,null,{s33:true}))).toEqual(s33RecoveryHashes);
 const p=candidate(),before=JSON.stringify(p);check(p);expect(JSON.stringify(p)).toBe(before);
 p.exceptions.forEach((e,i)=>{if(!indices.includes(i))expect(e).toEqual(baseline.exceptions[i]);});
 let updated=bytes;indices.forEach((_,i)=>updated=updated.replace(record(s33RecoveryOld[i]),record(s33RecoveryNew[i])));
 expect(withoutS33PolicyBytesForTest(updated)).toBe(withoutS33PolicyBytesForTest(bytes));
 expect(()=>withoutS33PolicyBytesForTest(updated.replace(record(s33RecoveryNew[0]),record(s33RecoveryNew[0]).replace('    {','   {')))).toThrow();
});
it('current unbound policy and every original approval remain valid and untouched',()=>{const p=JSON.parse(readFileSync(new URL('../nyay66-policy.json',import.meta.url)));check(p);});
it.each([0,1])('rejects altered, partial, duplicated or relocated replacement %i',i=>{
 for(const change of [e=>e.reason+=' widened',e=>e.approvalPr=95,e=>e.referenceSha256='a'.repeat(64),e=>e.liveSha256='b'.repeat(64),e=>e.checks=['pixels'],e=>e.checks.push('accessibility'),e=>e.theme='dark',e=>e.viewport='mobile360',e=>e.extra=true]){const p=candidate();change(p.exceptions[indices[i]]);expect(()=>check(p)).toThrow();}
 const partial=candidate();partial.exceptions[indices[i]]=s33RecoveryOld[i];expect(()=>check(partial)).toThrow();
 const missing=candidate();missing.exceptions.splice(indices[i],1);expect(()=>check(missing)).toThrow();
 const duplicate=candidate();duplicate.exceptions.push(s33RecoveryNew[i]);expect(()=>check(duplicate)).toThrow();
 const moved=candidate();moved.exceptions.unshift(moved.exceptions.splice(indices[i],1)[0]);expect(()=>check(moved)).toThrow();
});
it.each(baseline.exceptions.map((_,i)=>i).filter(i=>!indices.includes(i)))('preserves historical record %i against mutation, deletion and duplication',i=>{
 for(const action of ['mutate','remove','duplicate']){const p=candidate();if(action==='mutate')p.exceptions[i].reason+=' widened';else if(action==='remove')p.exceptions.splice(i,1);else p.exceptions.push(structuredClone(p.exceptions[i]));expect(()=>{check(p);expect(p.exceptions.filter((_,n)=>!indices.includes(n))).toEqual(baseline.exceptions.filter((_,n)=>!indices.includes(n)));}).toThrow();}
});
it.each([0,1])('still requires exact owner, PR and digest approval for replacement %i',i=>{
 const e=s33RecoveryNew[i],c={id:1,approvalPr:94,user:{login:'rajeevbarnwal'},body:`NYAY66-EXCEPTION ${s33RecoveryHashes[i]}`};expect(approveException(e,[c],{s33:true})).toBe(true);
 for(const comments of [[],[{...c,id:0}],[{...c,approvalPr:95}],[{...c,user:{login:'other'}}],[{...c,body:'approved'}],[{...c,body:`NYAY66-EXCEPTION ${s33RecoveryHashes[1-i]}`}],[{...c,body:`NYAY66-EXCEPTION ${approveException(s33RecoveryOld[i],null,{s33:true})}`}]] )expect(()=>finalizeEnforcement([],{enforced:[],exceptions:[e]},comments,{s33:true})).toThrow('OWNER_EXCEPTION_APPROVAL_MISSING');
});
