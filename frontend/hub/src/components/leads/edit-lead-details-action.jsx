import { useEffect, useId, useState } from 'react';
import { Loader2Icon, PencilIcon } from 'lucide-react';

import { FormDialog } from '@/components/form-dialog';
import { CustomSourceInput } from '@/components/leads/custom-source-input';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import api from '@/lib/api';
import { can, isAdmin, PERMISSIONS } from '@/lib/access';
import { CLASSES, OTHER_SOURCE, SOURCE_FILTERS, SYLLABI, customSourceError, enquiryError } from '@/lib/enquiries';
import { leadUrl } from '@/lib/leads';

const options = (values) => values.map((value) => ({ value, label: value }));
const SECTIONS = {
  parent: {
    title: 'Parent',
    description: 'Update the parent’s contact details for this enquiry.',
    fields: [
      {
        name: 'parent_name',
        label: 'Parent name',
        maxLength: 255,
        required: true,
        wide: true,
      },
      {
        name: 'phone_dial_code',
        label: 'Country calling code',
        maxLength: 5,
        inputMode: 'tel',
        required: true,
      },
      {
        name: 'phone_number',
        label: 'Phone number',
        maxLength: 30,
        inputMode: 'tel',
        required: true,
      },
      {
        name: 'parent_email',
        label: 'Email',
        maxLength: 254,
        type: 'email',
        wide: true,
      },
      { name: 'country', label: 'Country', maxLength: 100, wide: true },
    ],
  },
  student: {
    title: 'Student',
    description: 'Update the student’s details for this enquiry.',
    fields: [
      {
        name: 'student_name',
        label: 'Student name',
        maxLength: 255,
        required: true,
        wide: true,
      },
      {
        name: 'grade',
        label: 'Class',
        options: options(CLASSES),
        required: true,
      },
      { name: 'syllabus', label: 'Syllabus', options: options(SYLLABI) },
      { name: 'school_name', label: 'School', maxLength: 255, wide: true },
    ],
  },
  lead: {
    title: 'Lead',
    description:
      'Correct the original enquiry source. Ownership, status and captured campaign tags are managed separately.',
    fields: [
      {
        name: 'source',
        label: 'Original enquiry source',
        required: true,
        wide: true,
        options: SOURCE_FILTERS.filter(({ value }) => !['DEMO_LINK', 'DIAGNOSTIC_LINK'].includes(value)),
      },
      // Other's own name: shown, required and sent only while Other is chosen.
      { name: 'custom_source', customSource: true, shownWhen: (form) => form.source === OTHER_SOURCE },
    ],
  },
};
const NONE = '__none__';
const shown = (fields, form) => fields.filter((field) => !field.shownWhen || field.shownWhen(form));

/** Loaded afresh on each open; the PATCH includes only fields changed in this card. */
function EditLeadDetailsDialog({ leadId, section, onClose, onSaved }) {
  const config = SECTIONS[section];
  const formId = useId();
  const [saved, setSaved] = useState(null);
  const [form, setForm] = useState({});
  const [pending, setPending] = useState(false);
  const [error, setError] = useState(null);
  const [fieldErrors, setFieldErrors] = useState({});
  const [loading, setLoading] = useState(true);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    api
      .get(leadUrl(leadId))
      .then(({ data }) => {
        if (!active) return;
        const values = Object.fromEntries(
          config.fields.map(({ name }) => [name, (name === 'source' ? data.original_source : data[name]) ?? ''])
        );
        setSaved(values);
        setForm(values);
      })
      .catch((err) => {
        if (active) setError(enquiryError(err, 'Could not load the current details.').message);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [leadId, config, reloadKey]);

  function setField(name, value) {
    setForm((current) => {
      const next = { ...current, [name]: value };
      // Leaving Other clears its name; coming back to it restores the saved one, if any.
      if (name === 'source' && 'custom_source' in current) {
        next.custom_source = value === OTHER_SOURCE && saved?.source === OTHER_SOURCE ? saved.custom_source : '';
      }
      return next;
    });
    setFieldErrors((current) => ({ ...current, [name]: null, ...(name === 'source' ? { custom_source: null } : {}) }));
  }

  async function handleSubmit(event) {
    event.preventDefault();
    if (!saved || pending || loading) return;
    const fields = shown(config.fields, form);
    // An Other source needs its name once anything about it changes; one
    // saved before names were is left as it is while untouched.
    if ('custom_source' in form && (form.source !== saved.source || form.custom_source !== saved.custom_source)) {
      const problem = customSourceError(form.source, form.custom_source);
      if (problem) {
        setFieldErrors((current) => ({ ...current, custom_source: problem }));
        return;
      }
    }
    const changes = Object.fromEntries(
      fields.flatMap(({ name }) => {
        if (form[name] === saved[name]) return [];
        const value = form[name].trim();
        return value === saved[name] ? [] : [[name, value]];
      })
    );
    if (!Object.keys(changes).length) {
      onClose();
      return;
    }
    setPending(true);
    setError(null);
    setFieldErrors({});
    try {
      const { data } = await api.patch(leadUrl(leadId), changes);
      onSaved?.(data, `${config.title} details updated.`);
      onClose();
    } catch (err) {
      const failure = enquiryError(err, 'Could not save the details.');
      setError(failure.message);
      setFieldErrors(
        Object.fromEntries(
          Object.entries(failure.fields).map(([key, value]) => [
            key === 'phone' ? 'phone_number' : key,
            Array.isArray(value) ? value[0] : String(value),
          ])
        )
      );
    } finally {
      setPending(false);
    }
  }

  return (
    <FormDialog
      open
      onOpenChange={(next) => {
        if (!next && !pending) onClose();
      }}
      title={`Edit ${config.title.toLowerCase()} details`}
      description={config.description}
      error={error}
      formId={formId}
      confirmLabel="Save"
      pending={pending}
      confirmDisabled={loading || !saved}
      size="lg"
    >
      {loading ? (
        <p className="text-muted-foreground flex items-center gap-2 py-4 text-sm" role="status">
          <Loader2Icon className="size-4 animate-spin" /> Loading current details…
        </p>
      ) : !saved ? (
        <Button variant="outline" onClick={() => setReloadKey((key) => key + 1)}>
          Retry
        </Button>
      ) : (
        <form id={formId} onSubmit={handleSubmit} className="max-h-[60vh] overflow-y-auto py-1" noValidate>
          <fieldset className="grid gap-4 sm:grid-cols-2" disabled={pending}>
            {shown(config.fields, form).map((field) => {
              const id = `${formId}-${field.name}`;
              const errorId = `${id}-error`;
              const value = form[field.name];
              if (field.customSource) {
                return (
                  <CustomSourceInput
                    key={field.name}
                    id={id}
                    value={value}
                    onChange={(next) => setField(field.name, next)}
                    error={fieldErrors[field.name]}
                    disabled={pending}
                  />
                );
              }
              const choices = field.options && [...field.options];
              // Keep legacy values visible without silently replacing them on a partial save.
              if (choices && value && !choices.some((option) => option.value === value)) {
                choices.push({ value, label: value });
              }
              return (
                <div key={field.name} className={`grid content-start gap-2 ${field.wide ? 'sm:col-span-2' : ''}`}>
                  <Label htmlFor={id} required={field.required}>
                    {field.label}
                  </Label>
                  {choices ? (
                    <Select
                      value={value || NONE}
                      onValueChange={(next) => setField(field.name, next === NONE ? '' : next)}
                      disabled={pending}
                    >
                      <SelectTrigger
                        id={id}
                        className="w-full"
                        aria-required={field.required || undefined}
                        aria-invalid={!!fieldErrors[field.name]}
                        aria-describedby={fieldErrors[field.name] ? errorId : undefined}
                      >
                        <SelectValue placeholder={`Choose ${field.label.toLowerCase()}`} />
                      </SelectTrigger>
                      <SelectContent>
                        {!field.required || !value ? (
                          <SelectItem value={NONE}>{field.required ? 'Choose…' : 'Not set'}</SelectItem>
                        ) : null}
                        {choices.map((option) => (
                          <SelectItem key={option.value} value={option.value}>
                            {option.label}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  ) : (
                    <Input
                      id={id}
                      value={value}
                      onChange={(event) => setField(field.name, event.target.value)}
                      maxLength={field.maxLength}
                      type={field.type ?? 'text'}
                      inputMode={field.inputMode}
                      autoComplete="off"
                      aria-required={field.required || undefined}
                      aria-invalid={!!fieldErrors[field.name]}
                      aria-describedby={fieldErrors[field.name] ? errorId : undefined}
                    />
                  )}
                  {fieldErrors[field.name] ? (
                    <p id={errorId} className="text-destructive text-sm" role="alert">
                      {fieldErrors[field.name]}
                    </p>
                  ) : null}
                </div>
              );
            })}
          </fieldset>
        </form>
      )}
    </FormDialog>
  );
}

/** The API enforces the same Admin role and existing lead permissions. */
export function EditLeadDetailsAction({ user, leadId, section, onSaved, label = 'Edit' }) {
  const [open, setOpen] = useState(false);
  if (!leadId || !isAdmin(user) || !can(user, PERMISSIONS.viewAllLeads) || !can(user, PERMISSIONS.addLead)) return null;
  return (
    <>
      <Button variant="outline" size="sm" aria-label={`Edit ${section} details`} onClick={() => setOpen(true)}>
        <PencilIcon />
        {label}
      </Button>
      {open ? (
        <EditLeadDetailsDialog
          key={`${leadId}-${section}`}
          leadId={leadId}
          section={section}
          onClose={() => setOpen(false)}
          onSaved={onSaved}
        />
      ) : null}
    </>
  );
}
