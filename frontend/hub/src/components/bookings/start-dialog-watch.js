import { createContext } from 'react';

/**
 * Told whether a Start Demo / Start Diagnostic dialog (StartBookingButton) is
 * open, by a page that reads its booking again on its own -- so a fresh read
 * never takes the dialog, and the refusal it shows, away. Null (nobody
 * listening) unless a page provides it.
 */
export const StartDialogWatch = createContext(null);
