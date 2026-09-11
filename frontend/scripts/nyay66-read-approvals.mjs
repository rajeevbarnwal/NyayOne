import {readFile,writeFile} from 'node:fs/promises';
import {execFileSync} from 'node:child_process';
const config=JSON.parse(await readFile('scripts/nyay66-policy.json'));
const comments=[];
for(const pr of new Set(config.exceptions.map(entry=>entry.approvalPr))){
  if(!Number.isSafeInteger(pr)||pr<1)throw Error('INVALID_EXCEPTION_PR');
  const pages=JSON.parse(execFileSync('gh',['api','--paginate','--slurp',`repos/rajeevbarnwal/NyayOne/issues/${pr}/comments`],{encoding:'utf8',maxBuffer:4*1024*1024}));
  comments.push(...pages.flat());
}
await writeFile(process.env.NYAY66_COMMENTS,JSON.stringify(comments),{mode:0o600});
