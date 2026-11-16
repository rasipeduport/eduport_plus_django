import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import {
  AlertCircleIcon,
  BadgePercentIcon,
  FileSearchIcon,
  FileTextIcon,
  LayersIcon,
  ListOrderedIcon,
  Loader2Icon,
  PlusIcon,
  SaveIcon,
  SendIcon,
  XIcon,
} from 'lucide-react';

import api from '@/lib/api';
import {
  BOARDS,
  GRADES,
  MAX_INCLUSIONS,
  PDF_PREVIEW_URL,
  PLAN_TYPES,
  PRICING_URL,
  STRUCTURES,
  STRUCTURE_PLAN_TYPES,
  SUBTITLES,
  SYLLABI_URL,
  SYLLABUS_VERSIONS,
  apiFieldErrors,
  defaultInclusions,
  draftUrl,
  emptyForm,
  formErrors,
  formFrom,
  formatAmount,
  packagePrices,
  packageTitleFor,
  payloadOf,
  salesError,
  sameContent,
  syllabusUrl,
} from '@/lib/sales';
import { useFlashNotice } from '@/hooks/use-flash-notice';
import { useLeaveGuard } from '@/hooks/use-leave-guard';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { FormDialog } from '@/components/form-dialog';
import { Page, PageHeader } from '@/components/page/page';
import { AccessDeniedState, ErrorState, Notice } from '@/components/page/states';
import { WorkspaceCard } from '@/components/bookings/redemo-workspace/parts';
import { ChapterEditor } from '@/components/sales/chapter-editor';
import { PackageCards } from '@/components/sales/package-cards';
import { SyllabusStatusBadge } from '@/components/sales/syllabus-badges';
import { PublishDialog, SimilarWarning, SyllabusActionDialog } from '@/components/sales/syllabus-dialogs';
import { useSyllabusPdf } from '@/components/sales/syllabus-pdf';
import { cn } from '@/lib/utils';

// Where each of the form's errors is shown: the id of the field to focus.
const FIELD_IDS = {
  title: 'syllabus-title',
  grade: 'syllabus-grade',
  board: 'syllabus-board',
  syllabus_version: 'syllabus-version',
  structure: 'syllabus-structure-CHAPTER_WISE',
  subtitle: 'syllabus-subtitle',
  package_title: 'syllabus-package-title',
  plan_types: 'plan-type-REGULAR',
  inclusions: 'inclusion-0',
  chapters: 'add-chapter',
};
const fieldId = (key) => FIELD_IDS[key] ?? (key.startsWith('chapters.') ? `chapter-${key.split('.').slice(1).join('-')}` : null);

function FieldError({ message }) {
  return message ? <p className="text-destructive text-sm">{message}</p> : null;
}

function OptionSelect({ id, value, onChange, placeholder, options, disabled, invalid }) {
  return (
    <Select value={value} onValueChange={onChange} disabled={disabled}>
      <SelectTrigger id={id} className="w-full" aria-required="true" aria-invalid={invalid ? true : undefined}>
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

/** A choice drawn as a card: a radio (one structure) or a checkbox (several plan types). */
function ChoiceCard({ type, id, name, checked, onChange, disabled, label, description }) {
  return (
    <label
      htmlFor={id}
      className={cn(
        'flex cursor-pointer items-start gap-3 rounded-lg border p-3 transition-colors',
        checked ? 'border-primary bg-primary/5' : 'hover:bg-accent',
        disabled && 'cursor-not-allowed opacity-60 hover:bg-transparent'
      )}
    >
      <input
        type={type}
        id={id}
        name={name}
        checked={checked}
        onChange={onChange}
        disabled={disabled}
        className="accent-primary mt-0.5 size-4 shrink-0"
      />
      <span className="min-w-0">
        <span className="block text-sm font-medium">{label}</span>
        <span className="text-muted-foreground block text-sm">{description}</span>
      </span>
    </label>
  );
}

function EditorSkeleton() {
  return (
    <div className="grid gap-4" aria-busy="true">
      {[0, 1, 2].map((index) => (
        <Skeleton key={index} className="h-48 w-full rounded-xl" />
      ))}
    </div>
  );
}

/**
 * Writing a syllabus: a new one (/sales-syllabus/new, saved as its draft
 * revision 1) or the draft of an existing one (/sales-syllabus/:id/edit) --
 * its titles, grade and board, its chapters, the plan types it is sold as,
 * the packages page's inclusions -- with its packages priced as you type at
 * the pricing in effect, a preview of the PDF parents receive, and, on
 * explicit confirmation, publishing it (D4). A published syllabus's draft
 * never touches its published revision until that confirmation. Unsaved
 * changes are guarded like a report's (TutorReportPage).
 */
export default function SalesSyllabusEditorPage() {
  const { syllabusId } = useParams();
  const creating = !syllabusId;
  const navigate = useNavigate();

  const [detail, setDetail] = useState(null);
  const [form, setForm] = useState(() => (creating ? emptyForm() : null));
  const [baseline, setBaseline] = useState(() => (creating ? emptyForm() : null));
  const [failure, setFailure] = useState(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [pricing, setPricing] = useState(undefined); // undefined: loading; null: none set up yet
  const [pricingFailed, setPricingFailed] = useState(false);
  const [pricingKey, setPricingKey] = useState(0);
  // The form's own checks run as it changes once a save or preview has found something
  // (`checked`); the API's field errors (`serverErrors`) hold until the form changes.
  const [checked, setChecked] = useState(false);
  const [serverErrors, setServerErrors] = useState({});
  const [saveError, setSaveError] = useState(null);
  const [pending, setPending] = useState(false);
  const [notice, setNotice] = useFlashNotice();
  const [publishing, setPublishing] = useState(false);
  const [starting, setStarting] = useState(false);
  const [discarding, setDiscarding] = useState(null); // 'leave' | 'reload'
  const [focusRequest, setFocusRequest] = useState(null);
  const leaving = useRef(null);
  const pdf = useSyllabusPdf();
  // A save that answers after the Admin has left must not bring them back (or touch the gone page).
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  // The syllabus and its draft (editing), or nothing to load (creating).
  useEffect(() => {
    if (creating) return undefined;
    let active = true;
    api
      .get(syllabusUrl(syllabusId))
      .then((response) => {
        if (!active) return;
        setDetail(response.data);
        setFailure(null);
        if (response.data.draft) {
          const loaded = formFrom(response.data.draft);
          setForm(loaded);
          setBaseline(loaded);
        }
      })
      .catch((err) => {
        if (active) setFailure(salesError(err, 'Could not load the syllabus.'));
      });
    return () => {
      active = false;
    };
  }, [creating, syllabusId, reloadKey]);

  // The pricing in effect, for the packages section.
  useEffect(() => {
    let active = true;
    setPricing(undefined);
    setPricingFailed(false);
    api
      .get(PRICING_URL)
      .then((response) => {
        if (active) setPricing(response.data?.current ?? null);
      })
      .catch(() => {
        if (!active) return;
        setPricing(null);
        setPricingFailed(true);
      });
    return () => {
      active = false;
    };
  }, [pricingKey]);

  const [prevForm, setPrevForm] = useState(form);
  if (form !== prevForm) {
    setPrevForm(form);
    setServerErrors({});
    if (saveError && saveError.code !== 'DRAFT_CHANGED') setSaveError(null);
  }
  const errors = { ...(checked && form ? formErrors(form) : {}), ...serverErrors };

  const dirty = Boolean(form && baseline && !sameContent(form, baseline));

  // Unsaved changes are kept in memory only: leaving the page by reload or close asks first.
  useEffect(() => {
    if (!dirty) return undefined;
    const warn = (event) => {
      event.preventDefault();
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [dirty]);

  // Leaving by a link, the browser's Back or Forward, or logging out asks too.
  useLeaveGuard(dirty, (proceed) => {
    leaving.current = proceed;
    setDiscarding('leave');
  });

  // A field with a problem gets the focus once the form is enabled again.
  useEffect(() => {
    if (!focusRequest || pending) return undefined;
    const timer = setTimeout(() => {
      const element = document.getElementById(fieldId(focusRequest) ?? '');
      element?.focus();
      element?.scrollIntoView?.({ block: 'center' });
      setFocusRequest(null);
    }, 0);
    return () => clearTimeout(timer);
  }, [focusRequest, pending]);

  const set = (field, value) => setForm((current) => ({ ...current, [field]: value }));
  const focusFirst = (found) => {
    const first = Object.keys(found)[0];
    if (first) setFocusRequest(first);
  };
  /** Whether the form passes its own checks; if not, they show from now on and the first gets the focus. */
  const passesChecks = () => {
    const found = formErrors(form);
    if (!Object.keys(found).length) return true;
    setChecked(true);
    focusFirst(found);
    return false;
  };

  const setStructure = (structure) =>
    setForm((current) => ({ ...current, structure, plan_types: [...STRUCTURE_PLAN_TYPES[structure]].slice(0, 3) }));
  const setBoard = (board) =>
    setForm((current) => {
      // The inclusions follow the board while they are still the reference's ("Structured CBSE aligned learning").
      const untouched = JSON.stringify(current.inclusions) === JSON.stringify(defaultInclusions(current.board));
      return { ...current, board, inclusions: untouched ? defaultInclusions(board) : current.inclusions };
    });
  const togglePlanType = (planType) =>
    setForm((current) => ({
      ...current,
      plan_types: current.plan_types.includes(planType)
        ? current.plan_types.filter((value) => value !== planType)
        : [...current.plan_types, planType],
    }));

  /** Save the form: create the syllabus, or save its draft. Answers the syllabus as saved, or null. */
  const save = async () => {
    if (!passesChecks()) {
      setSaveError('Check the highlighted fields.');
      return null;
    }
    setPending(true);
    setSaveError(null);
    setServerErrors({});
    try {
      if (creating) {
        const response = await api.post(SYLLABI_URL, payloadOf(form));
        if (!alive.current) return null;
        setBaseline(form); // nothing unsaved: leaving for the draft's own page asks nothing
        if (leaving.current) {
          // The Admin asked to leave while it saved: it is saved, so they go where they were going.
          const proceed = leaving.current;
          leaving.current = null;
          setDiscarding(null);
          proceed();
          return response.data;
        }
        navigate(`/sales-syllabus/${response.data.id}/edit`, {
          replace: true,
          state: { notice: 'Saved as a draft. Preview it, then publish it when it is ready.' },
        });
        return response.data;
      }
      const response = await api.put(draftUrl(syllabusId), { ...payloadOf(form), updated_at: detail.draft.updated_at });
      if (!alive.current) return null;
      const saved = formFrom(response.data.draft);
      setDetail(response.data);
      setForm(saved);
      setBaseline(saved);
      setNotice(
        response.data.published
          ? `Draft revision ${response.data.draft.number} saved. The published revision ${response.data.published.number} is unchanged.`
          : `Draft revision ${response.data.draft.number} saved.`
      );
      if (leaving.current) {
        // The Admin asked to leave while it saved: it is saved, so they go where they were going
        // (and nothing else -- Save and publish stops here).
        const proceed = leaving.current;
        leaving.current = null;
        setDiscarding(null);
        proceed();
        return null;
      }
      return response.data;
    } catch (err) {
      if (!alive.current) return null;
      const refused = salesError(err, 'Could not save the syllabus.');
      setSaveError(refused);
      const fieldErrors = apiFieldErrors(refused.fields);
      setServerErrors(fieldErrors);
      focusFirst(fieldErrors);
      return null;
    } finally {
      if (alive.current) setPending(false);
    }
  };

  const saveAndPublish = async () => {
    if (dirty || creating) {
      const saved = await save();
      if (!saved || creating) return;
    }
    setPublishing(true);
  };

  const previewPdf = () => {
    if (!passesChecks()) return;
    pdf.preview({ url: PDF_PREVIEW_URL, data: payloadOf(form) });
  };

  const discard = () => {
    const proceed = leaving.current;
    leaving.current = null;
    const reloading = discarding === 'reload';
    setDiscarding(null);
    setForm(baseline);
    if (reloading) {
      setSaveError(null);
      setReloadKey((key) => key + 1);
    } else {
      proceed?.();
    }
  };

  // ------------------------------------------------------------- what to show
  const backLink = creating ? '/sales-syllabus' : `/sales-syllabus/${syllabusId}`;
  let body;
  if (failure?.status === 403) {
    body = <AccessDeniedState title="You don't have access to syllabuses." message={failure.message} />;
  } else if (failure) {
    body = <ErrorState message={failure.message} onRetry={() => setReloadKey((key) => key + 1)} />;
  } else if (!creating && !detail) {
    body = <EditorSkeleton />;
  } else if (!creating && detail.status === 'INACTIVE') {
    body = (
      <ErrorState message="This syllabus is inactive. Reactivate it from its page before editing it." />
    );
  } else if (!creating && !detail.draft) {
    body = (
      <WorkspaceCard icon={FileTextIcon} title="No draft yet">
        <p className="text-muted-foreground text-sm">
          Revision {detail.published?.number} is published and stays as it is. Start a draft to change it: you publish
          the draft when it is ready.
        </p>
        <div>
          <Button onClick={() => setStarting(true)}>Start a draft</Button>
        </div>
      </WorkspaceCard>
    );
  } else {
    const bridge = form.structure === 'BRIDGE_COURSE';
    const locked = Boolean(detail?.structure_locked);
    const planTypes = bridge ? ['BRIDGE_COURSE'] : form.plan_types;
    const packages = pricing ? packagePrices(planTypes, form.chapters, pricing) : [];
    const draft = detail?.draft;
    const published = detail?.published;
    body = (
      <form
        className="grid gap-4"
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          save();
        }}
      >
        <WorkspaceCard icon={FileTextIcon} title="1. Basic information">
          <div className="grid gap-4 md:grid-cols-2">
            <div className="grid gap-2 md:col-span-2">
              <Label htmlFor="syllabus-title" required>
                Title
              </Label>
              <Input
                id="syllabus-title"
                value={form.title}
                onChange={(event) => set('title', event.target.value)}
                placeholder="Grade 6 CBSE"
                maxLength={120}
                aria-required="true"
                aria-invalid={errors.title ? true : undefined}
                aria-describedby="syllabus-title-help"
                disabled={pending}
              />
              <p id="syllabus-title-help" className="text-muted-foreground text-xs">
                The blue heading of the PDF, exactly as you type it.
              </p>
              <FieldError message={errors.title} />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="syllabus-grade" required>
                Grade
              </Label>
              <OptionSelect
                id="syllabus-grade"
                value={form.grade}
                onChange={(value) => set('grade', value)}
                placeholder="Choose the grade"
                options={GRADES}
                disabled={pending}
                invalid={errors.grade}
              />
              <FieldError message={errors.grade} />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="syllabus-board" required>
                Board / curriculum
              </Label>
              <OptionSelect
                id="syllabus-board"
                value={form.board}
                onChange={setBoard}
                placeholder="Choose the board"
                options={BOARDS}
                disabled={pending}
                invalid={errors.board}
              />
              <FieldError message={errors.board} />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="syllabus-version">Syllabus version</Label>
              <Input
                id="syllabus-version"
                list="syllabus-version-options"
                value={form.syllabus_version}
                onChange={(event) => set('syllabus_version', event.target.value)}
                placeholder="New Syllabus"
                maxLength={50}
                aria-invalid={errors.syllabus_version ? true : undefined}
                disabled={pending}
              />
              <datalist id="syllabus-version-options">
                {SYLLABUS_VERSIONS.map((version) => (
                  <option key={version} value={version} />
                ))}
              </datalist>
              <FieldError message={errors.syllabus_version} />
            </div>
            <fieldset className="grid gap-2 md:col-span-2" disabled={pending || locked}>
              <legend className="mb-2 text-sm font-medium">Structure</legend>
              <div className="grid gap-2 sm:grid-cols-2">
                {STRUCTURES.map((structure) => (
                  <ChoiceCard
                    key={structure.value}
                    type="radio"
                    id={`syllabus-structure-${structure.value}`}
                    name="structure"
                    checked={form.structure === structure.value}
                    onChange={() => setStructure(structure.value)}
                    disabled={pending || locked}
                    label={structure.label}
                    description={structure.description}
                  />
                ))}
              </div>
              {locked ? (
                <p className="text-muted-foreground text-xs">The structure is fixed once a syllabus is published.</p>
              ) : null}
              <FieldError message={errors.structure} />
            </fieldset>
            <div className="grid gap-2">
              <Label htmlFor="syllabus-subtitle">Line under the title</Label>
              <Input
                id="syllabus-subtitle"
                value={form.subtitle}
                onChange={(event) => set('subtitle', event.target.value)}
                placeholder={SUBTITLES[form.structure]}
                maxLength={120}
                aria-invalid={errors.subtitle ? true : undefined}
                disabled={pending}
              />
              <FieldError message={errors.subtitle} />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="syllabus-package-title">Packages page title</Label>
              <Input
                id="syllabus-package-title"
                value={form.package_title}
                onChange={(event) => set('package_title', event.target.value)}
                placeholder={packageTitleFor(form.title.trim())}
                maxLength={160}
                aria-invalid={errors.package_title ? true : undefined}
                disabled={pending}
              />
              <FieldError message={errors.package_title} />
            </div>
          </div>
        </WorkspaceCard>

        <WorkspaceCard icon={ListOrderedIcon} title={bridge ? '2. Days' : '2. Chapters'}>
          <ChapterEditor
            structure={form.structure}
            chapters={form.chapters}
            onChange={(chapters) => set('chapters', chapters)}
            errors={errors}
            disabled={pending}
          />
        </WorkspaceCard>

        <WorkspaceCard icon={LayersIcon} title="3. Plan types">
          {bridge ? (
            <p className="text-muted-foreground text-sm">
              A Bridge Course is sold as the whole course, or by the day: BDEs choose any of its days when quoting,
              priced per class. Keep every day here.
            </p>
          ) : (
            <fieldset className="grid gap-2 sm:grid-cols-2" disabled={pending}>
              <legend className="sr-only">Plan types this syllabus is sold as</legend>
              {PLAN_TYPES.filter((planType) => STRUCTURE_PLAN_TYPES.CHAPTER_WISE.includes(planType.value)).map((planType) => (
                <ChoiceCard
                  key={planType.value}
                  type="checkbox"
                  id={`plan-type-${planType.value}`}
                  checked={form.plan_types.includes(planType.value)}
                  onChange={() => togglePlanType(planType.value)}
                  disabled={pending}
                  label={planType.label}
                  description={planType.description}
                />
              ))}
            </fieldset>
          )}
          <FieldError message={errors.plan_types} />
        </WorkspaceCard>

        <WorkspaceCard
          icon={BadgePercentIcon}
          title="4. Pricing"
          action={
            <Button variant="link" size="sm" className="h-auto px-0" asChild>
              <Link to="/sales-pricing">Global pricing</Link>
            </Button>
          }
        >
          {pricingFailed ? (
            // Inside the form, so its button must not submit it (the shared ErrorState's would).
            <div
              role="alert"
              className="border-destructive/30 bg-destructive/5 flex flex-wrap items-center gap-3 rounded-xl border px-4 py-3"
            >
              <AlertCircleIcon className="text-destructive size-4 shrink-0" aria-hidden="true" />
              <p className="min-w-0 flex-1 text-sm">Could not load the pricing.</p>
              <Button type="button" variant="outline" size="sm" onClick={() => setPricingKey((key) => key + 1)}>
                Try again
              </Button>
            </div>
          ) : pricing === undefined ? (
            <Skeleton className="h-24 w-full" />
          ) : pricing ? (
            <>
              <p className="text-muted-foreground text-sm">
                Priced at pricing version {pricing.version}: {formatAmount(pricing.offer_fee, pricing.currency)} a class
                (standard {formatAmount(pricing.standard_fee, pricing.currency)}). The PDF uses the pricing in effect when
                it is drawn.
              </p>
              <PackageCards packages={packages} currency={pricing.currency} />
            </>
          ) : (
            <p className="text-sm">
              No pricing is set up yet, so packages cannot be priced and PDFs cannot be drawn.{' '}
              <Link to="/sales-pricing" className="font-medium underline">
                Set up the pricing
              </Link>
            </p>
          )}
          <fieldset className="mt-2 grid gap-2" disabled={pending}>
            <legend className="mb-1 text-sm font-medium">Inclusions on the packages page</legend>
            {form.inclusions.map((line, index) => (
              <div key={index} className="flex gap-2">
                <Input
                  id={`inclusion-${index}`}
                  value={line}
                  onChange={(event) =>
                    set('inclusions', form.inclusions.map((item, at) => (at === index ? event.target.value : item)))
                  }
                  maxLength={120}
                  aria-label={`Inclusion ${index + 1}`}
                />
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  onClick={() => set('inclusions', form.inclusions.filter((_, at) => at !== index))}
                  aria-label={`Remove inclusion ${index + 1}`}
                >
                  <XIcon className="size-4" />
                </Button>
              </div>
            ))}
            <div>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => set('inclusions', [...form.inclusions, ''])}
                disabled={form.inclusions.length >= MAX_INCLUSIONS}
              >
                <PlusIcon />
                Add inclusion
              </Button>
            </div>
            <FieldError message={errors.inclusions} />
          </fieldset>
        </WorkspaceCard>

        <WorkspaceCard icon={FileSearchIcon} title="5. PDF preview">
          <p className="text-muted-foreground text-sm">
            See the PDF parents receive, drawn from this form as it is now — saved or not.
          </p>
          <div className="flex flex-wrap items-center gap-3">
            <Button type="button" variant="outline" onClick={previewPdf} disabled={Boolean(pdf.pending) || pending}>
              {pdf.pending ? <Loader2Icon className="size-4 animate-spin" /> : <FileSearchIcon className="size-4" />}
              {pdf.pending ? 'Drawing the PDF…' : 'Preview PDF'}
            </Button>
          </div>
          {pdf.error ? (
            <p role="alert" className="text-destructive text-sm">
              {pdf.error}
            </p>
          ) : null}
        </WorkspaceCard>

        <WorkspaceCard icon={SendIcon} title="6. Publish">
          <p className="text-muted-foreground text-sm">
            {creating
              ? 'Save the syllabus as a draft first. Publishing it later makes it available for sale.'
              : published
                ? `Revision ${published.number} is published. Publishing this draft (revision ${draft.number}) replaces it for the sales to come; revision ${published.number} stays in the history.`
                : `Revision ${draft.number} is a draft. Publishing it makes the syllabus available for sale.`}
          </p>
          {detail?.reference ? (
            <p className="text-sm">
              Loaded from the reference PDF <span className="font-medium">{detail.reference}</span>: check it against that
              PDF before publishing.
            </p>
          ) : null}
          {detail ? (
            <SimilarWarning
              similar={detail.similar}
              subject={detail.draft ? `Draft revision ${detail.draft.number}` : null}
            />
          ) : null}
          {saveError ? (
            <div role="alert" className="text-destructive text-sm">
              {typeof saveError === 'string' ? saveError : saveError.message}{' '}
              {saveError.code === 'DRAFT_CHANGED' ? (
                <button type="button" className="font-medium underline" onClick={() => setDiscarding('reload')}>
                  Reload the latest version
                </button>
              ) : null}
            </div>
          ) : null}
          <div className="flex flex-wrap gap-2">
            <Button type="submit" variant="outline" disabled={pending || (!dirty && !creating)}>
              {pending ? <Loader2Icon className="size-4 animate-spin" /> : <SaveIcon className="size-4" />}
              {pending ? 'Saving…' : 'Save draft'}
            </Button>
            {!creating ? (
              <Button type="button" onClick={saveAndPublish} disabled={pending}>
                <SendIcon className="size-4" />
                {dirty ? 'Save and publish…' : 'Publish…'}
              </Button>
            ) : null}
          </div>
        </WorkspaceCard>
      </form>
    );
  }

  const title = creating ? 'New syllabus' : detail?.draft?.title || detail?.published?.title || 'Syllabus';
  return (
    <Page className="max-w-5xl">
      <PageHeader
        title={creating ? 'New syllabus' : `Edit ${title}`}
        description={
          creating
            ? 'Create a syllabus as a draft: its chapters, the plans it is sold as and the PDF parents receive.'
            : detail?.draft
              ? `Draft revision ${detail.draft.number}${dirty ? ' — unsaved changes' : ''}.`
              : null
        }
        actions={
          <>
            {detail ? <SyllabusStatusBadge status={detail.status} draftRevision={detail.draft?.number} /> : null}
            <Button variant="outline" asChild>
              <Link to={backLink}>{creating ? 'Cancel' : 'Back to syllabus'}</Link>
            </Button>
          </>
        }
        actionsClassName="items-center"
      />

      {notice ? <Notice onDismiss={() => setNotice(null)}>{notice}</Notice> : null}

      {body}

      {!creating ? (
        <PublishDialog
          syllabusId={syllabusId}
          seen={detail?.draft ?? null}
          open={publishing}
          onOpenChange={setPublishing}
          onStale={() => setSaveError({ code: 'DRAFT_CHANGED', message: 'This draft was changed meanwhile.' })}
          onPublished={(published) => {
            if (!alive.current) return; // the Admin has left meanwhile: never bring them back
            setBaseline(form);
            navigate(`/sales-syllabus/${syllabusId}`, {
              state: { notice: `Revision ${published.published.number} is published. It is what BDEs sell from now on.` },
            });
          }}
        />
      ) : null}
      <SyllabusActionDialog
        action={starting ? 'startDraft' : null}
        syllabus={detail}
        onOpenChange={(open) => {
          if (!open) setStarting(false);
        }}
        onDone={(updated) => {
          setDetail(updated);
          const loaded = formFrom(updated.draft);
          setForm(loaded);
          setBaseline(loaded);
          setNotice(`Draft revision ${updated.draft.number} started from the published version.`);
        }}
        onRefused={(refused) => {
          // Someone started the draft meanwhile: open theirs.
          if (refused.code !== 'DRAFT_EXISTS') return;
          setStarting(false);
          setReloadKey((key) => key + 1);
        }}
      />
      <FormDialog
        open={Boolean(discarding)}
        onOpenChange={(open) => {
          if (open) return;
          leaving.current = null;
          setDiscarding(null);
        }}
        title={discarding === 'reload' ? 'Reload the latest version?' : 'Discard your changes?'}
        description={
          discarding === 'reload'
            ? 'Your unsaved changes in this form will be replaced by the draft as it was saved most recently.'
            : pending
              ? 'Your changes are being saved. You will leave as soon as they are.'
              : 'Your changes to this syllabus have not been saved. They will be lost.'
        }
        confirmLabel={discarding === 'reload' ? 'Reload' : 'Discard changes'}
        confirmVariant="destructive"
        confirmDisabled={pending}
        cancelLabel="Keep editing"
        onConfirm={discard}
      />
      {pdf.dialog}
    </Page>
  );
}
