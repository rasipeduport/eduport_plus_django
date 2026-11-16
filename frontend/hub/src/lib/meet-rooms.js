// Where a class or a chapter exam is joined (backend accounts.meet_links): a
// normal session in the permanent Google Meet room of the tutor it is
// assigned to (`tutor_meet_link`), a chapter exam in the room of the mentor it
// is assigned to (`mentor_meet_link`), as the API returns them. Never the
// student's own link and never anyone else's: when the room is missing, the
// entry point says so instead of offering a Join that leads somewhere else.
import { isHttpsUrl } from './exam-status';

const room = (value) => {
  const link = (value || '').trim();
  return isHttpsUrl(link) ? link : null;
};

/** The room `session` is joined in -- its assigned tutor's Meet link -- or null. */
export function classMeetLink(session) {
  return room(session?.tutor_meet_link);
}

/** Why `session` has no room to join. */
export function classMeetMissing(session) {
  return session?.tutor_profile || session?.tutor ? "Tutor's Meet link not set" : 'No tutor assigned';
}

/** The room chapter exam `exam` is held in -- its assigned mentor's Meet link -- or null. */
export function examMeetLink(exam) {
  return room(exam?.mentor_meet_link);
}

/** Why `exam` has no room to join. */
export function examMeetMissing(exam) {
  return exam?.mentor_profile || exam?.mentor ? "Mentor's Meet link not set" : 'No mentor assigned';
}
