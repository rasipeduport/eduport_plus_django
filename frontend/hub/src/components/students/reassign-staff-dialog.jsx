import { useEffect, useState } from 'react';

import { FormDialog } from '@/components/form-dialog';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Label } from '@/components/ui/label';
import api from '@/lib/api';

// Radix Select disallows an empty-string value, so "no one" uses a sentinel.
const NOT_ASSIGNED_VALUE = '__not_assigned__';

// The slim /api/mentors and /api/tutors lists only carry assignable (active)
// staff. If the current assignee has since been deactivated, keep them in the
// options so the select shows who is assigned today instead of a blank.
function withCurrent(options, current) {
  if (!current || options.some((o) => o.id === current.id)) return options;
  return [current, ...options];
}

export function ReassignStaffDialog({ student, open, onOpenChange, onSaved }) {
  const currentMentor = student.mentor_profile ?? null;
  const currentTutor = student.tutor_profile ?? null;

  const [mentors, setMentors] = useState([]);
  const [tutors, setTutors] = useState([]);
  const [loaded, setLoaded] = useState(false);
  const [mentorId, setMentorId] = useState(currentMentor?.id ?? NOT_ASSIGNED_VALUE);
  const [tutorId, setTutorId] = useState(currentTutor?.id ?? NOT_ASSIGNED_VALUE);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // Re-sync selections from the student each time the dialog opens, so the
  // form reflects the latest saved assignment rather than stale local state.
  const [prevOpen, setPrevOpen] = useState(open);
  if (open !== prevOpen) {
    setPrevOpen(open);
    if (open) {
      setMentorId(currentMentor?.id ?? NOT_ASSIGNED_VALUE);
      setTutorId(currentTutor?.id ?? NOT_ASSIGNED_VALUE);
      setError(null);
    }
  }

  // Load the mentor/tutor option lists the first time the dialog is opened.
  useEffect(() => {
    if (!open || loaded) return undefined;
    let cancelled = false;
    Promise.allSettled([api.get('/api/mentors/'), api.get('/api/tutors/')]).then(([mentorsResult, tutorsResult]) => {
      if (cancelled) return;
      if (mentorsResult.status === 'fulfilled') setMentors(mentorsResult.value.data.mentors ?? []);
      if (tutorsResult.status === 'fulfilled') setTutors(tutorsResult.value.data.tutors ?? []);
      if (mentorsResult.status === 'rejected' || tutorsResult.status === 'rejected') {
        setError('Failed to load mentors and tutors.');
      }
      setLoaded(true);
    });
    return () => {
      cancelled = true;
    };
  }, [open, loaded]);

  const staffLoading = !loaded;
  const toId = (value) => (value === NOT_ASSIGNED_VALUE ? null : value);
  const changed = toId(mentorId) !== (currentMentor?.id ?? null) || toId(tutorId) !== (currentTutor?.id ?? null);

  async function handleSave() {
    setLoading(true);
    setError(null);
    try {
      await api.post('/api/students/reassign/', {
        id: student.id,
        mentor: toId(mentorId),
        tutor: toId(tutorId),
      });
      onSaved?.();
      onOpenChange(false);
    } catch (err) {
      setError(err.response?.data?.message || 'Failed to reassign mentor/tutor.');
    } finally {
      setLoading(false);
    }
  }

  return (
    <FormDialog
      open={open}
      onOpenChange={onOpenChange}
      title="Reassign Mentor / Tutor"
      description={`Change the mentor or tutor for ${student.full_name}.`}
      error={error}
      onConfirm={handleSave}
      confirmLabel="Save"
      pending={loading}
      confirmDisabled={staffLoading || !changed}
    >
      <div className="space-y-4 py-2">
        <div className="space-y-2">
          <Label htmlFor="reassign-mentor">Mentor</Label>
          <Select value={mentorId} onValueChange={setMentorId} disabled={staffLoading}>
            <SelectTrigger id="reassign-mentor" className="w-full">
              <SelectValue placeholder="Select mentor" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={NOT_ASSIGNED_VALUE}>Not assigned</SelectItem>
              {withCurrent(mentors, currentMentor).map((m) => (
                <SelectItem key={m.id} value={m.id}>
                  {m.full_name || m.email}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-2">
          <Label htmlFor="reassign-tutor">Tutor</Label>
          <Select value={tutorId} onValueChange={setTutorId} disabled={staffLoading}>
            <SelectTrigger id="reassign-tutor" className="w-full">
              <SelectValue placeholder="Select tutor" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={NOT_ASSIGNED_VALUE}>Not assigned</SelectItem>
              {withCurrent(tutors, currentTutor).map((t) => (
                <SelectItem key={t.id} value={t.id}>
                  {t.full_name || t.email}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <p className="text-muted-foreground text-xs">
          Past records keep the previous staff. Upcoming scheduled sessions move to the new tutor.
        </p>
      </div>
    </FormDialog>
  );
}
