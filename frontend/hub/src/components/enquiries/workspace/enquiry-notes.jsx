import { enquiryNotesUrl } from '@/lib/enquiries';
import { LeadNotes } from '@/components/notes/lead-notes';

/**
 * The notes staff keep on this enquiry -- its BDE, the tutors teaching its
 * bookings and the administrators -- oldest first, with a box to add one (GET
 * and POST /api/bde/enquiries/<id>/notes/; components/notes/lead-notes). Notes
 * belong to the enquiry, so its Demo and Diagnostic bookings share them; they
 * are never shown to the parent or the student, and are kept as written. Read
 * when the tab opens.
 */
export function EnquiryNotes({ enquiryId }) {
  return (
    <LeadNotes
      url={enquiryNotesUrl(enquiryId)}
      emptyDescription="Notes you, the tutor and the administrators add to this enquiry appear here, oldest first."
      placeholder="Write a note for the tutor and the administrators…"
      loadError="Could not load this enquiry's notes."
    />
  );
}
