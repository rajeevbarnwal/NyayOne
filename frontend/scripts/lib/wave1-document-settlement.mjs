// Harness lifecycle barrier, not an error filter. Runtime listeners stay armed.
export async function leaveSettledDocument(page, depart) {
  try {
    await page.evaluate(async () => {
      // An interaction/server projection can introduce a font after the earlier
      // screen-readiness sample. Flush layout before waiting for the live set.
      document.body?.getBoundingClientRect();
      await document.fonts.ready;
      await new Promise((resolveFrame) => requestAnimationFrame(
        () => requestAnimationFrame(resolveFrame),
      ));
      document.body?.getBoundingClientRect();
      await document.fonts.ready;
    });
  } catch {
    throw new Error('WAVE1_DOCUMENT_SETTLEMENT_FAILED');
  }
  return depart();
}
