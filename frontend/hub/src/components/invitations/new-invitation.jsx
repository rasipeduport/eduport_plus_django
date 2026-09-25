import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { ChevronDownIcon, InfoIcon, PlusIcon } from 'lucide-react';

import api from '@/lib/api';
import { cn } from '@/lib/utils';
import { useIsMobile } from '@/hooks/use-mobile';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog';
import {
  Drawer,
  DrawerClose,
  DrawerContent,
  DrawerFooter,
  DrawerHeader,
  DrawerTitle,
  DrawerTrigger,
} from '@/components/ui/drawer';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';

const MEET_URL_REGEX = /^https:\/\/meet\.google\.com\/[a-zA-Z0-9]([a-zA-Z0-9-]+[a-zA-Z0-9])?$/;

function isValidMeetUrl(url) {
  return MEET_URL_REGEX.test(url);
}

const ROLES = ['admin', 'mentor', 'tutor', 'student'];
const NOT_ASSIGNED_VALUE = '__not_assigned__';

/**
 * "New Invitation" trigger plus the creation form, as a dialog on desktop and
 * a bottom drawer on mobile.
 *
 * Other areas (students, admins, mentors, tutors) do not embed this form --
 * they link to `/invitations?role=<role>&open=true`, which lands here with the
 * right role preselected and the form already open. Those params are stripped
 * once consumed so a refresh does not reopen the form.
 */
export function NewInvitation({ initialRole, initialOpen = false, onSuccess }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const [open, setOpen] = useState(initialOpen);
  const isMobile = useIsMobile();

  // Clean up the URL params once the form has been opened via a redirect.
  useEffect(() => {
    if (initialOpen) {
      const next = new URLSearchParams(searchParams);
      next.delete('open');
      next.delete('role');
      setSearchParams(next, { replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleSuccess = () => {
    setOpen(false);
    onSuccess?.();
  };

  const title = 'Create New Invitation';
  const formProps = { onSuccess: handleSuccess, initialRole };

  if (!isMobile) {
    return (
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogTrigger asChild>
          <Button>
            <PlusIcon />
            New Invitation
          </Button>
        </DialogTrigger>
        <DialogContent className="sm:max-w-[425px]">
          <DialogHeader>
            <DialogTitle>{title}</DialogTitle>
          </DialogHeader>
          <InvitationForm {...formProps} />
        </DialogContent>
      </Dialog>
    );
  }

  return (
    <Drawer open={open} onOpenChange={setOpen}>
      <DrawerTrigger asChild>
        <Button>
          <PlusIcon />
          New Invitation
        </Button>
      </DrawerTrigger>
      <DrawerContent>
        <DrawerHeader className="text-left">
          <DrawerTitle>{title}</DrawerTitle>
        </DrawerHeader>
        <div className="overflow-y-auto">
          <InvitationForm className="px-4" {...formProps} />
        </div>
        <DrawerFooter className="pt-2">
          <DrawerClose asChild>
            <Button variant="outline">Cancel</Button>
          </DrawerClose>
        </DrawerFooter>
      </DrawerContent>
    </Drawer>
  );
}

function InvitationForm({ className, onSuccess, initialRole }) {
  const normalizedInitialRole = (initialRole || '').toLowerCase();

  const [email, setEmail] = useState('');
  const [studentId, setStudentId] = useState('');
  const [role, setRole] = useState(ROLES.includes(normalizedInitialRole) ? normalizedInitialRole : 'admin');
  const [loading, setLoading] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  const [verifiedStudent, setVerifiedStudent] = useState(null);
  const [mentors, setMentors] = useState([]);
  const [mentorId, setMentorId] = useState(NOT_ASSIGNED_VALUE);
  const [tutors, setTutors] = useState([]);
  const [tutorId, setTutorId] = useState(NOT_ASSIGNED_VALUE);
  const [meetLink, setMeetLink] = useState('');
  const [whatsappGroupCreated, setWhatsappGroupCreated] = useState(false);

  // Reset verification state whenever the role or student ID changes.
  // Adjusting state during render, guarded by the previous values, is
  // React's recommended alternative to a synchronizing effect.
  const resetKey = `${role} ${studentId}`;
  const [prevResetKey, setPrevResetKey] = useState(resetKey);
  if (resetKey !== prevResetKey) {
    setPrevResetKey(resetKey);
    setVerifiedStudent(null);
    setMentorId(NOT_ASSIGNED_VALUE);
    setTutorId(NOT_ASSIGNED_VALUE);
    setMeetLink('');
    setWhatsappGroupCreated(false);
    setSuccess('');
    setError('');
  }

  const selectedMentor = mentors.find((m) => m.id === mentorId);
  const mentorLabel =
    mentorId === NOT_ASSIGNED_VALUE
      ? 'Not Assigned'
      : selectedMentor?.full_name || selectedMentor?.email || 'Select mentor';

  const selectedTutor = tutors.find((t) => t.id === tutorId);
  const tutorLabel =
    tutorId === NOT_ASSIGNED_VALUE ? 'Not Assigned' : selectedTutor?.full_name || selectedTutor?.email || 'Select tutor';

  const handleVerify = async () => {
    const trimmed = studentId.trim();
    if (!trimmed) {
      setError('Please enter a student ID');
      return;
    }

    setVerifying(true);
    setError('');
    setSuccess('');

    // The lookup decides success; the staff lists are best-effort so a failing
    // mentors/tutors call still leaves a usable form.
    const [lookupResult, mentorsResult, tutorsResult] = await Promise.allSettled([
      api.post('/api/invitations/lookup-student/', { student_code: trimmed }),
      api.get('/api/mentors/'),
      api.get('/api/tutors/'),
    ]);

    try {
      if (lookupResult.status === 'rejected') {
        const response = lookupResult.reason?.response;
        setError(response?.data?.message || 'Failed to verify student');
        return;
      }

      const studentData = lookupResult.value.data.student_data;
      setVerifiedStudent(studentData);
      setSuccess(`Fetched ${studentData.full_name || studentData.student_code} successfully!`);

      setMentors(mentorsResult.status === 'fulfilled' ? mentorsResult.value.data.mentors ?? [] : []);

      // Preselect the tutor named on the enrolment sheet when we can match one.
      let matchedTutorId = NOT_ASSIGNED_VALUE;
      if (tutorsResult.status === 'fulfilled') {
        const fetchedTutors = tutorsResult.value.data.tutors ?? [];
        setTutors(fetchedTutors);

        const sheetTutorName = (studentData.tutor_name || '').trim().toLowerCase();
        if (sheetTutorName) {
          const matchedTutor = fetchedTutors.find(
            (t) => (t.full_name || '').trim().toLowerCase() === sheetTutorName
          );
          if (matchedTutor) matchedTutorId = matchedTutor.id;
        }
      } else {
        setTutors([]);
      }
      setTutorId(matchedTutorId);
    } finally {
      setVerifying(false);
    }
  };

  const handleSubmit = async (event) => {
    event.preventDefault();

    if (role !== 'student' && !email.trim()) {
      setError('Please enter an email address');
      return;
    }

    if (role === 'student') {
      if (!studentId.trim()) {
        setError('Please enter a student ID');
        return;
      }

      if (!verifiedStudent) {
        setError('Please verify the student ID first');
        return;
      }

      if (meetLink.trim() && !isValidMeetUrl(meetLink.trim())) {
        setError('Invalid Google Meet URL. It should look like https://meet.google.com/abc-defg-hij');
        return;
      }
    }

    setLoading(true);
    setError('');
    setSuccess('');

    // Unlike the Hub, this backend does not re-read the enrolment sheet on
    // create -- the verified record is forwarded as the invitation payload.
    const payload =
      role === 'student'
        ? {
            role,
            email: verifiedStudent.email,
            full_name: verifiedStudent.full_name,
            student_code: verifiedStudent.student_code,
            mobile_number: verifiedStudent.mobile_number,
            country: verifiedStudent.country,
            state: verifiedStudent.state,
            school_name: verifiedStudent.school_name,
            grade: verifiedStudent.grade,
            syllabus: verifiedStudent.syllabus,
            admission_date: verifiedStudent.admission_date,
            remarks: verifiedStudent.remarks,
            mentor_id: mentorId !== NOT_ASSIGNED_VALUE ? mentorId : null,
            tutor_id: tutorId !== NOT_ASSIGNED_VALUE ? tutorId : null,
            meet_link: meetLink.trim() || null,
          }
        : { role, email: email.trim().toLowerCase() };

    try {
      await api.post('/api/invitations/', payload);

      setSuccess('Invitation created successfully!');
      setEmail('');
      setStudentId('');
      setVerifiedStudent(null);
      setMentorId(NOT_ASSIGNED_VALUE);
      setTutorId(NOT_ASSIGNED_VALUE);
      setMeetLink('');
      setWhatsappGroupCreated(false);

      setTimeout(() => onSuccess?.(), 500);
    } catch (err) {
      const data = err.response?.data;
      setError(
        data?.error === 'INVITATION_EXISTS'
          ? 'An invitation for this email already exists.'
          : data?.message || 'Failed to create invitation'
      );
    } finally {
      setLoading(false);
    }
  };

  const isStudentReady = role === 'student' && verifiedStudent !== null;

  return (
    <form onSubmit={handleSubmit} className={cn('grid gap-4', className)}>
      <div className="grid gap-2">
        <Label htmlFor="role">Role</Label>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="outline"
              className="w-full justify-between"
              type="button"
              disabled={loading || verifying}
            >
              <span className="capitalize">{role}</span>
              <ChevronDownIcon className="h-4 w-4 opacity-50" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent className="w-[var(--radix-dropdown-menu-trigger-width)]">
            {ROLES.map((option) => (
              <DropdownMenuItem key={option} className="capitalize" onClick={() => setRole(option)}>
                {option}
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      {role !== 'student' ? (
        <div className="grid gap-2">
          <Label htmlFor="email">Email</Label>
          <Input
            id="email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="user@example.com"
            disabled={loading}
            required
          />
        </div>
      ) : (
        <>
          <div className="grid gap-2">
            <Label htmlFor="student-id">Student ID</Label>
            <div className="flex gap-2">
              <Input
                id="student-id"
                type="text"
                value={studentId}
                onChange={(e) => setStudentId(e.target.value)}
                placeholder="EDP00099"
                disabled={loading || verifying}
                required
              />
              <Button
                type="button"
                variant="outline"
                onClick={handleVerify}
                disabled={loading || verifying || !studentId.trim() || isStudentReady}
              >
                {verifying ? 'Verifying...' : isStudentReady ? 'Verified' : 'Verify'}
              </Button>
            </div>
          </div>

          {isStudentReady && (
            <div className="grid gap-2">
              <Label htmlFor="mentor">Mentor</Label>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="outline" className="w-full justify-between" type="button" disabled={loading}>
                    <span className="truncate">{mentorLabel}</span>
                    <ChevronDownIcon className="h-4 w-4 shrink-0 opacity-50" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent className="max-h-64 w-[var(--radix-dropdown-menu-trigger-width)] overflow-y-auto">
                  <DropdownMenuItem onClick={() => setMentorId(NOT_ASSIGNED_VALUE)}>Not Assigned</DropdownMenuItem>
                  {mentors.map((m) => (
                    <DropdownMenuItem key={m.id} onClick={() => setMentorId(m.id)}>
                      {m.full_name || m.email}
                    </DropdownMenuItem>
                  ))}
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          )}

          {isStudentReady && (
            <div className="grid gap-2">
              <Label htmlFor="tutor">Tutor</Label>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="outline" className="w-full justify-between" type="button" disabled={loading}>
                    <span className="truncate">{tutorLabel}</span>
                    <ChevronDownIcon className="h-4 w-4 shrink-0 opacity-50" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent className="max-h-64 w-[var(--radix-dropdown-menu-trigger-width)] overflow-y-auto">
                  <DropdownMenuItem onClick={() => setTutorId(NOT_ASSIGNED_VALUE)}>Not Assigned</DropdownMenuItem>
                  {tutors.map((t) => (
                    <DropdownMenuItem key={t.id} onClick={() => setTutorId(t.id)}>
                      {t.full_name || t.email}
                    </DropdownMenuItem>
                  ))}
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          )}

          {isStudentReady && (
            <div className="grid gap-2">
              <Label htmlFor="meet-link">Google Meet Link</Label>
              <Input
                id="meet-link"
                type="url"
                value={meetLink}
                onChange={(e) => setMeetLink(e.target.value)}
                placeholder="https://meet.google.com/abc-defg-hij"
                disabled={loading}
              />
              <p className="text-muted-foreground flex items-start gap-1.5 text-xs">
                <InfoIcon className="mt-0.5 h-3 w-3 shrink-0" />
                <span>
                  Make sure the meeting is set to <strong className="text-foreground">Open</strong> so anyone with the
                  link can join.
                </span>
              </p>
            </div>
          )}
        </>
      )}

      {error && <p className="text-destructive text-sm">{error}</p>}
      {success && <p className="text-sm text-green-600">{success}</p>}

      {isStudentReady && (
        <label className="flex items-start gap-2 text-sm">
          <input
            type="checkbox"
            checked={whatsappGroupCreated}
            onChange={(e) => setWhatsappGroupCreated(e.target.checked)}
            disabled={loading}
            className="border-input mt-0.5 size-4 shrink-0 rounded-sm"
          />
          <span>Have you created the WhatsApp group for this student?</span>
        </label>
      )}

      <Button
        type="submit"
        disabled={loading || (role === 'student' && (!isStudentReady || !whatsappGroupCreated))}
        className="w-full"
      >
        {loading ? 'Creating...' : 'Create Invitation'}
      </Button>
    </form>
  );
}
