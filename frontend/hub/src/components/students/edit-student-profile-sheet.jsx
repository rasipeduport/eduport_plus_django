import { useState } from 'react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Sheet, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { cn } from '@/lib/utils';
import api from '@/lib/api';

// Profile columns the sheet edits, in display order. The student code and the
// sign-in email are shown but never sent: the code is the enrolment key and the
// email belongs to the sign-in provider (same rule as the staff details sheet).
const FIELDS = [
  { key: 'full_name', label: 'Name', placeholder: 'Full name', required: true },
  { key: 'mobile_number', label: 'Mobile number', placeholder: '+91 98765 43210', inputMode: 'tel' },
  { key: 'country', label: 'Country', half: true },
  { key: 'state', label: 'State', half: true },
  { key: 'school_name', label: 'School' },
  { key: 'grade', label: 'Grade', half: true },
  { key: 'syllabus', label: 'Syllabus', half: true },
  { key: 'admission_date', label: 'Admission date', type: 'date' },
];

function formFrom(student) {
  const values = {};
  for (const field of FIELDS) values[field.key] = student[field.key] ?? '';
  values.remarks_for_mentor = student.remarks_for_mentor ?? '';
  return values;
}

export function EditStudentProfileSheet({ student, open, onOpenChange, onSaved }) {
  const [form, setForm] = useState(() => formFrom(student));
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState('');

  // Re-sync the form from the student prop each time the sheet is opened.
  // Adjusting state during render, guarded by the previous open value, is
  // React's recommended alternative to a synchronizing effect.
  const [prevOpen, setPrevOpen] = useState(open);
  if (open !== prevOpen) {
    setPrevOpen(open);
    if (open) {
      setForm(formFrom(student));
      setError('');
    }
  }

  const setField = (key) => (event) => setForm((current) => ({ ...current, [key]: event.target.value }));

  const handleSubmit = async (event) => {
    event.preventDefault();
    setError('');

    if (!form.full_name.trim()) {
      setError('Name is required');
      return;
    }

    // Blank text clears the column; the API stores it as null.
    const payload = { id: student.id };
    for (const [key, value] of Object.entries(form)) payload[key] = value.trim() || null;

    setIsSaving(true);
    try {
      await api.put('/api/students/', payload);
      onSaved?.();
      onOpenChange(false);
    } catch (err) {
      setError(err.response?.data?.message || 'Failed to update student');
    } finally {
      setIsSaving(false);
    }
  };

  const email = student.profile?.email;

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="flex flex-col gap-0 sm:max-w-md">
        <SheetHeader>
          <SheetTitle>Edit Profile</SheetTitle>
          <SheetDescription>
            Update the enrolment details for {student.student_code}
            {email ? ` (${email})` : ''}. The student ID and sign-in email cannot be changed here.
          </SheetDescription>
        </SheetHeader>
        <form onSubmit={handleSubmit} className="flex flex-1 flex-col gap-4 overflow-y-auto px-4 pt-4">
          <div className="grid grid-cols-2 gap-4">
            {FIELDS.map((field) => (
              <div key={field.key} className={cn('grid gap-2', !field.half && 'col-span-2')}>
                <Label htmlFor={`profile-${field.key}`}>{field.label}</Label>
                <Input
                  id={`profile-${field.key}`}
                  type={field.type}
                  inputMode={field.inputMode}
                  value={form[field.key]}
                  onChange={setField(field.key)}
                  placeholder={field.placeholder}
                  disabled={isSaving}
                  required={field.required}
                />
              </div>
            ))}
            <div className="col-span-2 grid gap-2">
              <Label htmlFor="profile-remarks">Remarks for mentor</Label>
              <textarea
                id="profile-remarks"
                value={form.remarks_for_mentor}
                onChange={setField('remarks_for_mentor')}
                disabled={isSaving}
                rows={3}
                className="border-input placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-ring/50 dark:bg-input/30 w-full min-w-0 rounded-md border bg-transparent px-3 py-2 text-base shadow-xs outline-none transition-[color,box-shadow] focus-visible:ring-[3px] disabled:cursor-not-allowed disabled:opacity-50 md:text-sm"
              />
            </div>
          </div>
          {error && <p className="text-destructive text-sm">{error}</p>}
          <SheetFooter className="mt-auto px-0">
            <Button type="submit" disabled={isSaving}>
              {isSaving ? 'Saving...' : 'Save changes'}
            </Button>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={isSaving}>
              Cancel
            </Button>
          </SheetFooter>
        </form>
      </SheetContent>
    </Sheet>
  );
}
