import { useState } from 'react';
import { Link } from 'react-router-dom';

import { FormDialog } from '@/components/form-dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import api from '@/lib/api';
import { CLASSES, ENQUIRIES_URL, MANUAL_SOURCES, SYLLABI, enquiryError } from '@/lib/enquiries';

const FORM_ID = 'add-enquiry';
const EMPTY = {
  parent_name: '',
  phone_dial_code: '+91',
  phone_number: '',
  student_name: '',
  grade: '',
  source: '',
  school_name: '',
  syllabus: '',
  country: '',
};
// The API names a bad phone number 'phone' (backend bookings.leads); the form shows it under the number.
const FIELD_ALIASES = { phone: 'phone_number' };

function FieldError({ message }) {
  return message ? <p className="text-destructive text-sm">{message}</p> : null;
}

function firstMessage(value) {
  return Array.isArray(value) ? String(value[0] ?? '') : String(value ?? '');
}

function OptionSelect({ id, value, onChange, placeholder, options, disabled, required, invalid }) {
  return (
    <Select value={value} onValueChange={onChange} disabled={disabled}>
      <SelectTrigger
        id={id}
        className="w-full"
        aria-required={required ? 'true' : undefined}
        aria-invalid={invalid ? true : undefined}
      >
        <SelectValue placeholder={placeholder} />
      </SelectTrigger>
      <SelectContent>
        {options.map((option) => (
          <SelectItem key={option.value} value={option.value}>
            {option.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

/**
 * Adds an enquiry the BDE received outside their booking links -- a call, a
 * walk-in, a referral. It is theirs from the start; a parent who later books
 * through the booking pages lands on it and it stays theirs. The API refuses a
 * child already registered under the same phone number, pointing to the
 * enquiry only when it is the BDE's own.
 */
export function AddEnquiryDialog({ open, onOpenChange, onCreated }) {
  const [form, setForm] = useState(EMPTY);
  const [fieldErrors, setFieldErrors] = useState({});
  const [error, setError] = useState(null);
  const [pending, setPending] = useState(false);

  // A clean form on every open.
  const [prevOpen, setPrevOpen] = useState(open);
  if (open !== prevOpen) {
    setPrevOpen(open);
    if (open) {
      setForm(EMPTY);
      setFieldErrors({});
      setError(null);
    }
  }

  const setField = (name) => (event) => setForm((current) => ({ ...current, [name]: event.target.value }));
  const setChoice = (name) => (value) => setForm((current) => ({ ...current, [name]: value }));

  async function handleSubmit(event) {
    event.preventDefault();
    setError(null);

    const errors = {};
    if (!form.parent_name.trim()) errors.parent_name = "Enter the parent's name.";
    if (!/^\+[1-9]\d{0,3}$/.test(form.phone_dial_code.trim())) errors.phone_dial_code = 'Enter a country code, e.g. +91.';
    if (!form.phone_number.trim()) errors.phone_number = 'Enter the phone number.';
    if (!form.student_name.trim()) errors.student_name = "Enter the student's name.";
    if (!form.grade) errors.grade = 'Choose a class.';
    if (!form.source) errors.source = 'Choose how this enquiry reached you.';
    setFieldErrors(errors);
    if (Object.keys(errors).length) return;

    setPending(true);
    try {
      const body = Object.fromEntries(Object.entries(form).map(([key, value]) => [key, value.trim()]));
      const response = await api.post(ENQUIRIES_URL, body);
      onCreated?.(response.data);
      onOpenChange(false);
    } catch (err) {
      const failure = enquiryError(err, 'Could not add the enquiry.');
      if (failure.code === 'ENQUIRY_EXISTS') {
        setError(
          failure.enquiryId ? (
            <>
              {failure.message}{' '}
              <Link to={`/enquiries/${failure.enquiryId}`} className="underline" onClick={() => onOpenChange(false)}>
                Open it
              </Link>
            </>
          ) : (
            failure.message
          )
        );
        return;
      }
      const errors = {};
      for (const [field, value] of Object.entries(failure.fields)) {
        const name = FIELD_ALIASES[field] ?? field;
        if (name in EMPTY) errors[name] = firstMessage(value);
      }
      setFieldErrors(errors);
      if (!Object.keys(errors).length) setError(failure.message);
    } finally {
      setPending(false);
    }
  }

  const invalid = (name) => (fieldErrors[name] ? true : undefined);

  return (
    <FormDialog
      open={open}
      onOpenChange={onOpenChange}
      title="Add enquiry"
      description="An enquiry that reached you outside your booking links. It is added to your enquiries straight away."
      error={error}
      formId={FORM_ID}
      confirmLabel="Add enquiry"
      pendingLabel="Adding…"
      pending={pending}
      size="lg"
    >
      <form id={FORM_ID} onSubmit={handleSubmit} className="flex flex-col gap-4 py-1" noValidate>
        <fieldset className="grid gap-4" disabled={pending}>
          <legend className="text-muted-foreground mb-1 text-xs font-medium tracking-wide uppercase">Parent</legend>
          <div className="grid gap-2">
            <Label htmlFor="enquiry-parent-name" required>
              Parent name
            </Label>
            <Input
              id="enquiry-parent-name"
              value={form.parent_name}
              onChange={setField('parent_name')}
              placeholder="Full name"
              autoComplete="off"
              aria-required="true"
              aria-invalid={invalid('parent_name')}
            />
            <FieldError message={fieldErrors.parent_name} />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="enquiry-phone-number" required>
              Phone number
            </Label>
            <div className="flex gap-2">
              <Input
                id="enquiry-phone-code"
                value={form.phone_dial_code}
                onChange={setField('phone_dial_code')}
                className="w-20 shrink-0"
                inputMode="tel"
                aria-label="Country code"
                aria-required="true"
                aria-invalid={invalid('phone_dial_code')}
              />
              <Input
                id="enquiry-phone-number"
                value={form.phone_number}
                onChange={setField('phone_number')}
                placeholder="98765 43210"
                inputMode="tel"
                autoComplete="off"
                aria-required="true"
                aria-invalid={invalid('phone_number')}
              />
            </div>
            <FieldError message={fieldErrors.phone_dial_code || fieldErrors.phone_number} />
          </div>
        </fieldset>

        <fieldset className="grid gap-4" disabled={pending}>
          <legend className="text-muted-foreground mb-1 text-xs font-medium tracking-wide uppercase">Student</legend>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="grid content-start gap-2">
              <Label htmlFor="enquiry-student-name" required>
                Student name
              </Label>
              <Input
                id="enquiry-student-name"
                value={form.student_name}
                onChange={setField('student_name')}
                placeholder="Full name"
                autoComplete="off"
                aria-required="true"
                aria-invalid={invalid('student_name')}
              />
              <FieldError message={fieldErrors.student_name} />
            </div>
            <div className="grid content-start gap-2">
              <Label htmlFor="enquiry-grade" required>
                Class
              </Label>
              <OptionSelect
                id="enquiry-grade"
                value={form.grade}
                onChange={setChoice('grade')}
                placeholder="Choose a class"
                options={CLASSES.map((grade) => ({ value: grade, label: grade }))}
                disabled={pending}
                required
                invalid={invalid('grade')}
              />
              <FieldError message={fieldErrors.grade} />
            </div>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="grid content-start gap-2">
              <Label htmlFor="enquiry-school">School (optional)</Label>
              <Input
                id="enquiry-school"
                value={form.school_name}
                onChange={setField('school_name')}
                autoComplete="off"
                aria-invalid={invalid('school_name')}
              />
              <FieldError message={fieldErrors.school_name} />
            </div>
            <div className="grid content-start gap-2">
              <Label htmlFor="enquiry-syllabus">Syllabus (optional)</Label>
              <OptionSelect
                id="enquiry-syllabus"
                value={form.syllabus}
                onChange={setChoice('syllabus')}
                placeholder="Choose a syllabus"
                options={SYLLABI.map((syllabus) => ({ value: syllabus, label: syllabus }))}
                disabled={pending}
                invalid={invalid('syllabus')}
              />
              <FieldError message={fieldErrors.syllabus} />
            </div>
          </div>
        </fieldset>

        <fieldset className="grid gap-4 sm:grid-cols-2" disabled={pending}>
          <legend className="text-muted-foreground mb-1 text-xs font-medium tracking-wide uppercase">Enquiry</legend>
          <div className="grid content-start gap-2">
            <Label htmlFor="enquiry-source" required>
              Source
            </Label>
            <OptionSelect
              id="enquiry-source"
              value={form.source}
              onChange={setChoice('source')}
              placeholder="How did it reach you?"
              options={MANUAL_SOURCES}
              disabled={pending}
              required
              invalid={invalid('source')}
            />
            <FieldError message={fieldErrors.source} />
          </div>
          <div className="grid content-start gap-2">
            <Label htmlFor="enquiry-country">Country (optional)</Label>
            <Input
              id="enquiry-country"
              value={form.country}
              onChange={setField('country')}
              placeholder="e.g. India"
              autoComplete="off"
              aria-invalid={invalid('country')}
            />
            <FieldError message={fieldErrors.country} />
          </div>
        </fieldset>
      </form>
    </FormDialog>
  );
}
