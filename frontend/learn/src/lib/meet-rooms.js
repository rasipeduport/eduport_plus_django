// Where a class or a chapter exam is joined: a class in the Google Meet room
// of the tutor it is assigned to (`tutor_meet_link`), a chapter exam in the
// room of the mentor it is assigned to (`mentor_meet_link`), as the API
// returns them. Never the student's own link and never anyone else's: when
// the room is missing, the card says so and offers no Join.

const room = (value) => {
  const link = (value || '').trim();
  return /^https:\/\/\S+$/i.test(link) ? link : null;
};

/** The room `session` is joined in -- its assigned tutor's Meet link -- or null. */
export function classMeetLink(session) {
  return room(session?.tutor_meet_link);
}

/** Why `session` has no room to join, for the student. */
export function classMeetMissing(session) {
  return session?.tutor_profile
    ? "Your tutor's Meet link is not available yet. Please contact your mentor."
    : 'No tutor is assigned to this class yet. Please contact your mentor.';
}

/** The room chapter exam `exam` is held in -- its assigned mentor's Meet link -- or null. */
export function examMeetLink(exam) {
  return room(exam?.mentor_meet_link);
}

/** Why `exam` has no room to join, for the student. */
export function examMeetMissing(exam) {
  return exam?.mentor_profile
    ? "Your mentor's Meet link is not available yet. Please contact your mentor."
    : 'No mentor is assigned to this exam yet.';
}
