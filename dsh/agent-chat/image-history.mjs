// Proactive selection policy only. DSH's native image-offload plugin owns validation,
// durable projection, token accounting, placeholder rendering and budget-error recovery.
export function offloadPreviousImages(session, currentSeq, prefix) {
  if (!Number.isSafeInteger(currentSeq) || currentSeq < 0) return 0;
  const targets=[];
  for (const seq of session.surface.nodes) {
    if (seq >= currentSeq) continue;
    const event=session.eventAt(seq), source=event?.data?.source, first=event?.data?.content?.[0];
    if (event?.type!=='user/message' || event.surfaceOp!=='append' || source?.kind!=='user' ||
        typeof source.rpcId!=='string' || first?.type!=='text' || !first.text.startsWith(prefix)) continue;
    try {
      const control=JSON.parse(first.text.split('\n',1)[0].slice(prefix.length));
      if (control.version!==1 || control.sessionId!==session.id || control.rpcId!==source.rpcId) continue;
    } catch { continue; }
    const message=session.deriveEventMessage(event);
    const imageIndexes=[];let index=0;
    for (const block of message.content) {
      if (block.type!=='image') continue;
      if (block.offloaded!==true) imageIndexes.push(index);
      index++;
    }
    if (imageIndexes.length) targets.push({seq,imageIndexes});
  }
  if (targets.length) session.append('image/offload',{targets});
  return targets.reduce((n,t)=>n+t.imageIndexes.length,0);
}
