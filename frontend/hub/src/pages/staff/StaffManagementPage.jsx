import { useState, useEffect } from 'react';
import {
  Loader2, Search, Plus,
  ArrowUpDown, ChevronDown, Trash, Mail, ShieldAlert
} from 'lucide-react';
import * as Avatar from '@radix-ui/react-avatar';
import api from '../../lib/api';
import { formatDate, EMAIL_RE } from '../../lib/utils';
import NewInvitationModal from '../../components/NewInvitationModal';
import StaffActionsDropdown from '../../components/StaffActionsDropdown';

/**
 * Generic staff (Admin / Mentor / Tutor) management page.
 *
 * Behaviour is identical across the three roles; the per-role differences are
 * supplied via `config`:
 *   { entityLabel, endpoint, responseKey, initialRole, fallbackInitial, hasStudentsCount }
 *
 * `hasStudentsCount` (true for mentors/tutors) adds the "Assigned students"
 * column and enables the deactivate/reactivate lifecycle: staff are
 * soft-deactivated (access revoked, account and history kept), never
 * deleted, and a mentor/tutor with assigned students must hand them over to
 * a replacement first. Admins are peers — one admin never deactivates
 * another, so the admins page has no status actions at all.
 */
export default function StaffManagementPage({ config }) {
  const { entityLabel, endpoint, responseKey, initialRole, fallbackInitial, hasStudentsCount } = config;
  const entityLower = entityLabel.toLowerCase();

  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  // Table filters and visibility
  const [searchTerm, setSearchTerm] = useState('');
  const [showColumnsDropdown, setShowColumnsDropdown] = useState(false);
  const [visibleColumns, setVisibleColumns] = useState({
    avatar: true,
    full_name: true,
    email: true,
    mobile_number: true,
    created_at: true,
    invited_by: true,
    ...(hasStudentsCount ? { students_count: true } : {}),
    status: true,
  });

  // Invitation Modal triggers
  const [isInviteModalOpen, setIsInviteModalOpen] = useState(false);

  // Edit / lifecycle modal states
  const [modalType, setModalType] = useState(null); // 'edit_details' | 'deactivate' | 'reactivate' | 'edit_email' | 'withdraw'
  const [active, setActive] = useState(null);

  // Form input states
  const [fullNameVal, setFullNameVal] = useState('');
  const [mobileNumberVal, setMobileNumberVal] = useState('');
  const [editEmailVal, setEditEmailVal] = useState('');
  const [reasonVal, setReasonVal] = useState('');

  // Handover (deactivate) state: active replacement staff of the same role.
  const [replacements, setReplacements] = useState([]);
  const [replacementsLoaded, setReplacementsLoaded] = useState(false);
  const [replacementId, setReplacementId] = useState('');

  // Deactivated staff are hidden by default; admins reveal them to reactivate.
  const [showDeactivated, setShowDeactivated] = useState(false);

  const [saving, setSaving] = useState(false);
  const [modalError, setModalError] = useState('');
  const [currentUser, setCurrentUser] = useState(null);

  // Sorting
  const [sortField, setSortField] = useState('created_at');
  const [sortAsc, setSortAsc] = useState(false);

  useEffect(() => {
    fetchCurrentUser();
    fetchRows();
  }, []);

  const fetchCurrentUser = async () => {
    try {
      const response = await api.get('/api/auth/me/');
      setCurrentUser(response.data.user);
    } catch (err) {
      console.error('Failed to load current user details', err);
    }
  };

  const fetchRows = async () => {
    setLoading(true);
    setError('');
    try {
      const response = await api.get(endpoint);
      setRows(response.data[responseKey] || []);
    } catch (err) {
      setError(err.response?.data?.message || `Failed to fetch ${entityLower} accounts.`);
    } finally {
      setLoading(false);
    }
  };

  const openModal = (type, row) => {
    setModalType(type);
    setActive(row);
    setModalError('');
    setSaving(false);

    if (type === 'edit_details') {
      setFullNameVal(row.full_name || '');
      setMobileNumberVal(row.mobile_number || '');
    } else if (type === 'edit_email') {
      setEditEmailVal(row.email);
    } else if (type === 'deactivate') {
      setReasonVal('');
      setReplacementId('');
      setReplacements([]); // never show a previous row's (or a stale) list
      // A handover is required when this mentor/tutor still has assigned
      // students: load active same-role replacements (slim endpoint already
      // excludes deactivated staff).
      if (hasStudentsCount && (row.assigned_students_count ?? 0) > 0) {
        setReplacementsLoaded(false);
        api.get(`/api/${responseKey}/`)
          .then((res) => {
            setReplacements(res.data[responseKey] || []);
          })
          .catch(() => setModalError('Failed to load replacement options.'))
          .finally(() => setReplacementsLoaded(true));
      }
    }
  };

  const closeModal = () => {
    setModalType(null);
    setActive(null);
    setModalError('');
  };

  const handleEditDetails = async (e) => {
    e.preventDefault();
    if (!fullNameVal.trim()) {
      setModalError('Name is required');
      return;
    }
    setSaving(true);
    setModalError('');
    try {
      await api.patch(`/api/users/${active.id}/`, {
        full_name: fullNameVal.trim(),
        mobile_number: mobileNumberVal.trim() || null
      });
      fetchRows();
      closeModal();
    } catch (err) {
      setModalError(err.response?.data?.message || `Failed to update ${entityLower} details.`);
    } finally {
      setSaving(false);
    }
  };

  const needsHandover = hasStudentsCount && (active?.assigned_students_count ?? 0) > 0;

  const handleDeactivateUser = async () => {
    setSaving(true);
    setModalError('');
    try {
      // Hand over assigned students to the chosen replacement first; the
      // backend refuses to deactivate while active students are assigned.
      if (needsHandover) {
        if (!replacementId) {
          setModalError('Select a replacement first.');
          setSaving(false);
          return;
        }
        const reassignBody = initialRole === 'MENTOR'
          ? { new_mentor: replacementId }
          : { new_tutor: replacementId };
        await api.post(`/api/users/${active.id}/reassign/`, reassignBody);
      }
      await api.post(`/api/users/${active.id}/status/`, {
        action: 'deactivate',
        ...(reasonVal.trim() ? { reason: reasonVal.trim() } : {}),
      });
      fetchRows();
      closeModal();
    } catch (err) {
      setModalError(err.response?.data?.message || 'Failed to deactivate user.');
    } finally {
      setSaving(false);
    }
  };

  const handleReactivateUser = async () => {
    setSaving(true);
    setModalError('');
    try {
      await api.post(`/api/users/${active.id}/status/`, { action: 'reactivate' });
      fetchRows();
      closeModal();
    } catch (err) {
      setModalError(err.response?.data?.message || 'Failed to reactivate user.');
    } finally {
      setSaving(false);
    }
  };

  const handleEditEmail = async (e) => {
    e.preventDefault();
    if (!editEmailVal.trim() || !EMAIL_RE.test(editEmailVal.trim())) {
      setModalError('Please enter a valid email address.');
      return;
    }
    setSaving(true);
    setModalError('');
    try {
      await api.patch('/api/invitations/', {
        old_email: active.email,
        new_email: editEmailVal.trim().toLowerCase()
      });
      fetchRows();
      closeModal();
    } catch (err) {
      setModalError(err.response?.data?.message || 'Failed to update invitation email.');
    } finally {
      setSaving(false);
    }
  };

  const handleWithdrawInvitation = async () => {
    setSaving(true);
    setModalError('');
    try {
      await api.delete('/api/invitations/', {
        data: { email: active.email }
      });
      fetchRows();
      closeModal();
    } catch (err) {
      setModalError(err.response?.data?.message || 'Failed to withdraw invitation.');
    } finally {
      setSaving(false);
    }
  };

  const handleSort = (field) => {
    if (sortField === field) {
      setSortAsc(!sortAsc);
    } else {
      setSortField(field);
      setSortAsc(true);
    }
  };

  // Sorting and filtering
  const deactivatedCount = rows.filter((r) => r.kind !== 'ghost' && r.deactivated_at).length;
  const filteredRows = rows.filter(row =>
    (showDeactivated || row.kind === 'ghost' || !row.deactivated_at) &&
    (row.email.toLowerCase().includes(searchTerm.toLowerCase()) ||
      row.full_name.toLowerCase().includes(searchTerm.toLowerCase()))
  );

  const getSortedData = (dataList) => {
    return [...dataList].sort((a, b) => {
      let valA = a[sortField];
      let valB = b[sortField];

      if (sortField === 'invited_by') {
        valA = a.invited_by_profile?.full_name || a.invited_by_profile?.email || '';
        valB = b.invited_by_profile?.full_name || b.invited_by_profile?.email || '';
      }

      if (valA === null || valA === undefined) return sortAsc ? 1 : -1;
      if (valB === null || valB === undefined) return sortAsc ? -1 : 1;

      if (typeof valA === 'string') {
        return sortAsc
          ? valA.localeCompare(valB)
          : valB.localeCompare(valA);
      } else {
        return sortAsc ? valA - valB : valB - valA;
      }
    });
  };

  const toggleColumn = (col) => {
    setVisibleColumns(prev => ({ ...prev, [col]: !prev[col] }));
  };

  if (loading && rows.length === 0) {
    return (
      <div className="flex items-center justify-center h-96">
        <Loader2 className="h-8 w-8 animate-spin text-white" />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6 w-full max-w-full box-border">
      {/* Search and Columns buttons */}
      <div className="flex flex-col sm:flex-row gap-4 items-start sm:items-center justify-between">
        <div className="flex items-center gap-4 w-full sm:w-auto">
          <div className="relative flex-1 sm:w-80">
            <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-500" />
            <input
              type="text"
              placeholder="Filter by email or name..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="w-full pl-10 pr-4 h-10 bg-[#111] border border-[rgba(255,255,255,0.08)] rounded-xl text-sm text-white placeholder-zinc-500 focus:outline-none focus:ring-1 focus:ring-zinc-600 transition-all"
            />
          </div>

          <div className="relative">
            <button
              onClick={() => setShowColumnsDropdown(!showColumnsDropdown)}
              className="h-10 px-4 bg-[#111] border border-[rgba(255,255,255,0.08)] rounded-xl text-sm font-medium hover:bg-zinc-900 transition-colors flex items-center gap-2 text-zinc-300 hover:text-white"
            >
              Columns
              <ChevronDown className="w-4 h-4" />
            </button>

            {showColumnsDropdown && (
              <div className="absolute left-0 mt-1.5 w-48 bg-[#121214] border border-[#1e1e24] rounded-xl shadow-xl py-2 z-50">
                <div className="px-3 py-1 text-[10px] font-bold text-zinc-500 uppercase tracking-widest border-b border-[#1e1e24]/70 mb-2">
                  Toggle Columns
                </div>
                {Object.keys(visibleColumns).map(col => (
                  <label
                    key={col}
                    className="flex items-center gap-2.5 px-3 py-1.5 hover:bg-zinc-800 cursor-pointer text-xs text-zinc-300 hover:text-white"
                  >
                    <input
                      type="checkbox"
                      checked={visibleColumns[col]}
                      onChange={() => toggleColumn(col)}
                      className="rounded border-zinc-700 bg-zinc-950 text-white focus:ring-white/20"
                    />
                    <span className="capitalize">{col.replace(/_/g, ' ')}</span>
                  </label>
                ))}
              </div>
            )}
          </div>

          {deactivatedCount > 0 && (
            <button
              onClick={() => setShowDeactivated((v) => !v)}
              className="h-10 px-4 bg-[#111] border border-[rgba(255,255,255,0.08)] rounded-xl text-sm font-medium hover:bg-zinc-900 transition-colors text-zinc-300 hover:text-white whitespace-nowrap"
            >
              {showDeactivated ? 'Hide deactivated' : `Show deactivated (${deactivatedCount})`}
            </button>
          )}
        </div>

        {currentUser?.role === 'ADMIN' && (
          <button
            onClick={() => setIsInviteModalOpen(true)}
            className="h-10 px-4 bg-white hover:bg-zinc-200 text-zinc-950 rounded-xl text-sm font-semibold shadow-sm transition-all flex items-center gap-2 self-stretch sm:self-auto shrink-0 justify-center cursor-pointer"
          >
            <Plus className="w-4 h-4" />
            New {entityLabel}
          </button>
        )}
      </div>

      {error && (
        <div className="bg-red-950/40 text-red-400 text-xs p-3 rounded-lg border border-red-900/50">
          {error}
        </div>
      )}

      {/* Table */}
      <div className="border border-[rgba(255,255,255,0.08)] bg-[#0a0a0a] rounded-xl shadow-xl overflow-x-auto w-full">
          <table className="w-full text-left border-collapse text-sm">
            <thead>
              <tr className="border-b border-[rgba(255,255,255,0.08)] bg-[#0f0f0f]">
                {visibleColumns.avatar && <th className="h-12 px-6 font-semibold text-xs text-zinc-400 align-middle w-10"></th>}
                {visibleColumns.full_name && (
                  <th className="h-12 px-6 font-semibold text-xs text-zinc-400 align-middle">
                    <button onClick={() => handleSort('full_name')} className="flex items-center gap-1 hover:text-white">
                      Name
                      <ArrowUpDown className="w-3.5 h-3.5" />
                    </button>
                  </th>
                )}
                {visibleColumns.email && (
                  <th className="h-12 px-6 font-semibold text-xs text-zinc-400 align-middle">
                    <button onClick={() => handleSort('email')} className="flex items-center gap-1 hover:text-white">
                      Email
                      <ArrowUpDown className="w-3.5 h-3.5" />
                    </button>
                  </th>
                )}
                {visibleColumns.mobile_number && (
                  <th className="h-12 px-6 font-semibold text-xs text-zinc-400 align-middle">Phone</th>
                )}
                {visibleColumns.created_at && (
                  <th className="h-12 px-6 font-semibold text-xs text-zinc-400 align-middle">
                    <button onClick={() => handleSort('created_at')} className="flex items-center gap-1 hover:text-white">
                      Joined at
                      <ArrowUpDown className="w-3.5 h-3.5" />
                    </button>
                  </th>
                )}
                {visibleColumns.invited_by && (
                  <th className="h-12 px-6 font-semibold text-xs text-zinc-400 align-middle">
                    <button onClick={() => handleSort('invited_by')} className="flex items-center gap-1 hover:text-white">
                      Invited by
                      <ArrowUpDown className="w-3.5 h-3.5" />
                    </button>
                  </th>
                )}
                {hasStudentsCount && visibleColumns.students_count && (
                  <th className="h-12 px-6 font-semibold text-xs text-zinc-400 align-middle text-center">
                    <button onClick={() => handleSort('students_count')} className="flex items-center gap-1 mx-auto hover:text-white">
                      Assigned students
                      <ArrowUpDown className="w-3.5 h-3.5" />
                    </button>
                  </th>
                )}
                {visibleColumns.status && (
                  <th className="h-12 px-6 font-semibold text-xs text-zinc-400 align-middle">Status</th>
                )}
                <th className="h-12 px-2 w-10 sticky right-0 bg-[#0f0f0f] border-l border-[rgba(255,255,255,0.08)] z-20"></th>
              </tr>
            </thead>
            <tbody>
              {filteredRows.length === 0 ? (
                <tr>
                  <td colSpan="100%" className="py-8 text-center text-zinc-500 text-sm">
                    No {entityLower} accounts found matching search criteria.
                  </td>
                </tr>
              ) : (
                getSortedData(filteredRows).map(row => {
                  const initials = row.full_name?.split(' ').map(n => n[0]).join('').substring(0, 2) || fallbackInitial;
                  return (
                    <tr
                      key={row.id}
                      className="group hover:bg-[rgba(255,255,255,0.02)] border-b border-[rgba(255,255,255,0.08)] h-[54px] transition-colors"
                    >
                      {visibleColumns.avatar && (
                        <td className="py-2 px-6 align-middle">
                          {row.kind === 'ghost' ? (
                            <div className="w-8 h-8 rounded-full bg-zinc-800 text-zinc-400 flex items-center justify-center border border-zinc-700/50">
                              <Mail className="w-4 h-4" />
                            </div>
                          ) : (
                            <Avatar.Root className="relative flex h-8 w-8 shrink-0 overflow-hidden rounded-full border border-[rgba(255,255,255,0.1)]">
                              <Avatar.Image
                                src={row.avatar_url || undefined}
                                alt={row.full_name}
                                className="aspect-square h-full w-full object-cover"
                              />
                              <Avatar.Fallback className="flex h-full w-full items-center justify-center rounded-full bg-indigo-950 text-indigo-300 border border-indigo-900/50 text-xs font-semibold">
                                {initials}
                              </Avatar.Fallback>
                            </Avatar.Root>
                          )}
                        </td>
                      )}
                      {visibleColumns.full_name && (
                        <td className="py-2 px-6 font-medium text-white text-sm align-middle whitespace-nowrap">
                          {row.kind === 'ghost' ? (
                            <span className="text-zinc-500 italic font-normal">Invited</span>
                          ) : (
                            row.full_name || <span className="text-zinc-500">—</span>
                          )}
                        </td>
                      )}
                      {visibleColumns.email && (
                        <td className="py-2 px-6 text-white text-sm align-middle whitespace-nowrap">{row.email}</td>
                      )}
                      {visibleColumns.mobile_number && (
                        <td className="py-2 px-6 text-[#a1a1aa] text-sm align-middle whitespace-nowrap">
                          {row.kind === 'ghost' ? '—' : (row.mobile_number || '—')}
                        </td>
                      )}
                      {visibleColumns.created_at && (
                        <td className="py-2 px-6 text-[#a1a1aa] text-sm align-middle whitespace-nowrap">
                          {row.kind === 'ghost' ? '—' : formatDate(row.created_at)}
                        </td>
                      )}
                      {visibleColumns.invited_by && (
                        <td className="py-2 px-6 text-zinc-300 text-sm align-middle whitespace-nowrap">
                          {row.invited_by_profile?.full_name || row.invited_by_profile?.email || '—'}
                        </td>
                      )}
                      {hasStudentsCount && visibleColumns.students_count && (
                        <td className="py-2 px-6 text-zinc-300 text-sm align-middle text-center font-mono tabular-nums">
                          {row.kind === 'ghost' ? '—' : (row.assigned_students_count ?? 0)}
                        </td>
                      )}
                      {visibleColumns.status && (
                        <td className="py-2 px-6 align-middle whitespace-nowrap">
                          {row.kind === 'ghost' ? (
                            <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-zinc-900/80 text-zinc-400 border border-zinc-800/80">Invited</span>
                          ) : row.deactivated_at ? (
                            <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-zinc-900/80 text-zinc-400 border border-zinc-800/80" title={row.deactivated_at}>Deactivated</span>
                          ) : (
                            <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-emerald-950/80 text-emerald-400 border border-emerald-900/50">Active</span>
                          )}
                        </td>
                      )}
                      <td className="py-2 px-2 align-middle text-right sticky right-0 bg-[#0a0a0a] group-hover:bg-[#111] border-l border-[rgba(255,255,255,0.08)] transition-colors z-10">
                        {currentUser?.role === 'ADMIN' && (
                          <StaffActionsDropdown
                            items={row.kind === 'active' ? [
                              { label: 'Edit Details', onClick: () => openModal('edit_details', row) },
                              // Admins are peers: no deactivate/reactivate on the admins page.
                              ...(initialRole !== 'ADMIN' ? [
                                row.deactivated_at
                                  ? { label: 'Reactivate', onClick: () => openModal('reactivate', row) }
                                  : { label: 'Deactivate', onClick: () => openModal('deactivate', row), danger: true },
                              ] : []),
                            ] : [
                              { label: 'Edit Email', onClick: () => openModal('edit_email', row) },
                              { label: 'Withdraw Invitation', onClick: () => openModal('withdraw', row), danger: true },
                            ]}
                          />
                        )}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
      </div>

      {/* Modals */}
      {modalType && (
        <div className="fixed inset-0 bg-black/45 flex items-center justify-center z-50 p-4">

          {/* Edit Details Modal */}
          {modalType === 'edit_details' && (
            <div className="w-full max-w-sm bg-[#1c1c1c] border border-white/10 rounded-2xl p-6 shadow-2xl relative">
              <h3 className="text-base font-semibold text-white m-0">Edit Details</h3>
              <p className="text-xs text-zinc-400 mt-1 mb-6">Update name and phone number for {active?.email}.</p>

              <form onSubmit={handleEditDetails} className="space-y-4">
                {modalError && <p className="text-xs text-red-400 bg-red-950/40 p-2.5 rounded border border-red-900/50 m-0">{modalError}</p>}

                <div className="space-y-1.5">
                  <label htmlFor="edit-name" className="block text-xs font-bold text-zinc-400 uppercase tracking-widest">Name</label>
                  <input
                    id="edit-name"
                    type="text"
                    value={fullNameVal}
                    onChange={(e) => setFullNameVal(e.target.value)}
                    className="w-full px-3 py-2 bg-white/[0.04] border border-white/10 rounded-lg text-sm text-white focus:outline-none focus:ring-2 focus:ring-white/20"
                    disabled={saving}
                    required
                  />
                </div>

                <div className="space-y-1.5">
                  <label htmlFor="edit-phone" className="block text-xs font-bold text-zinc-400 uppercase tracking-widest">Phone Number</label>
                  <input
                    id="edit-phone"
                    type="text"
                    placeholder="+91 98765 43210"
                    value={mobileNumberVal}
                    onChange={(e) => setMobileNumberVal(e.target.value)}
                    className="w-full px-3 py-2 bg-white/[0.04] border border-white/10 rounded-lg text-sm text-white focus:outline-none focus:ring-2 focus:ring-white/20"
                    disabled={saving}
                  />
                </div>

                <div className="flex justify-end gap-3 pt-2">
                  <button
                    type="button"
                    onClick={closeModal}
                    className="px-4 py-2 text-xs font-semibold text-zinc-400 hover:text-white border border-white/10 rounded-lg hover:bg-white/10 transition-all cursor-pointer"
                    disabled={saving}
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    className="px-4 py-2 bg-white hover:bg-zinc-200 text-black text-xs font-semibold rounded-lg shadow-md transition-all flex items-center gap-1.5 cursor-pointer"
                    disabled={saving}
                  >
                    {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : null}
                    Save Changes
                  </button>
                </div>
              </form>
            </div>
          )}

          {/* Deactivate Modal */}
          {modalType === 'deactivate' && (
            <div className="w-full max-w-sm bg-[#1c1c1c] border border-white/10 rounded-2xl p-6 shadow-2xl relative">
              <h3 className="text-base font-semibold text-white m-0">Deactivate {entityLabel}</h3>
              <p className="text-xs text-zinc-400 mt-1.5 mb-4">
                This revokes <strong className="text-white font-semibold">{active?.full_name || active?.email}</strong>&apos;s access to the Hub. Their account and history are kept, and they can be reactivated later.
              </p>

              {needsHandover && (
                <div className="space-y-2 mb-4">
                  <div className="bg-zinc-900 text-zinc-400 rounded-md p-3.5 border border-white/5 text-xs leading-normal">
                    This {entityLower} is assigned to <strong className="text-white font-semibold">{active.assigned_students_count} {active.assigned_students_count === 1 ? 'student' : 'students'}</strong>. Choose a replacement {entityLower} to hand them over to before deactivating.
                  </div>
                  <label htmlFor="replacement-select" className="block text-xs font-bold text-zinc-400 uppercase tracking-widest">Reassign students to</label>
                  <select
                    id="replacement-select"
                    value={replacementId}
                    onChange={(e) => setReplacementId(e.target.value)}
                    disabled={!replacementsLoaded || saving}
                    className="w-full px-3 py-2 bg-white/[0.04] border border-white/10 rounded-lg text-sm text-white focus:outline-none focus:ring-2 focus:ring-white/20 disabled:opacity-60"
                  >
                    <option value="" className="bg-[#1c1c1c]">
                      {replacementsLoaded ? `Select a ${entityLower}` : 'Loading…'}
                    </option>
                    {replacements.filter((o) => o.id !== active?.id).map((o) => (
                      <option key={o.id} value={o.id} className="bg-[#1c1c1c]">
                        {o.full_name || o.email}
                      </option>
                    ))}
                  </select>
                </div>
              )}

              <div className="space-y-1.5 mb-4">
                <label htmlFor="deactivate-reason" className="block text-xs font-bold text-zinc-400 uppercase tracking-widest">Reason (optional)</label>
                <input
                  id="deactivate-reason"
                  type="text"
                  placeholder="e.g. Left the company"
                  value={reasonVal}
                  onChange={(e) => setReasonVal(e.target.value)}
                  maxLength={500}
                  disabled={saving}
                  className="w-full px-3 py-2 bg-white/[0.04] border border-white/10 rounded-lg text-sm text-white focus:outline-none focus:ring-2 focus:ring-white/20"
                />
              </div>

              {modalError && <p className="text-xs text-red-400 bg-red-950/40 p-2.5 rounded border border-red-900/50 mb-4">{modalError}</p>}

              <div className="flex justify-end gap-3">
                <button
                  onClick={closeModal}
                  className="px-4 py-2 text-xs font-semibold text-zinc-400 hover:text-white border border-white/10 rounded-lg hover:bg-white/10 transition-all cursor-pointer"
                  disabled={saving}
                >
                  Cancel
                </button>
                <button
                  onClick={handleDeactivateUser}
                  className="px-4 py-2 bg-red-600 hover:bg-red-700 text-white text-xs font-semibold rounded-lg shadow-md transition-all flex items-center gap-1.5 cursor-pointer disabled:opacity-60 disabled:cursor-not-allowed"
                  disabled={saving || (needsHandover && (!replacementsLoaded || !replacementId))}
                >
                  {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <ShieldAlert className="w-3.5 h-3.5" />}
                  {needsHandover ? 'Reassign & Deactivate' : 'Deactivate'}
                </button>
              </div>
            </div>
          )}

          {/* Reactivate Modal */}
          {modalType === 'reactivate' && (
            <div className="w-full max-w-sm bg-[#1c1c1c] border border-white/10 rounded-2xl p-6 shadow-2xl relative">
              <h3 className="text-base font-semibold text-white m-0">Reactivate {entityLabel}</h3>
              <p className="text-xs text-zinc-400 mt-1.5 mb-4">
                Restore <strong className="text-white font-semibold">{active?.full_name || active?.email}</strong>&apos;s access to the Hub. They will be able to sign in again immediately. You can re-assign students to them afterwards.
              </p>

              {modalError && <p className="text-xs text-red-400 bg-red-950/40 p-2.5 rounded border border-red-900/50 mb-4">{modalError}</p>}

              <div className="flex justify-end gap-3">
                <button
                  onClick={closeModal}
                  className="px-4 py-2 text-xs font-semibold text-zinc-400 hover:text-white border border-white/10 rounded-lg hover:bg-white/10 transition-all cursor-pointer"
                  disabled={saving}
                >
                  Cancel
                </button>
                <button
                  onClick={handleReactivateUser}
                  className="px-4 py-2 bg-white hover:bg-zinc-200 text-black text-xs font-semibold rounded-lg shadow-md transition-all flex items-center gap-1.5 cursor-pointer"
                  disabled={saving}
                >
                  {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : null}
                  Reactivate
                </button>
              </div>
            </div>
          )}

          {/* Edit Email Modal (Ghosts) */}
          {modalType === 'edit_email' && (
            <div className="w-full max-w-sm bg-[#1c1c1c] border border-white/10 rounded-2xl p-6 shadow-2xl relative">
              <h3 className="text-base font-semibold text-white m-0">Edit Whitelisted Email</h3>
              <p className="text-xs text-zinc-400 mt-1 mb-6">Correct typographical errors in the whitelisted email address.</p>

              <form onSubmit={handleEditEmail} className="space-y-4">
                {modalError && <p className="text-xs text-red-400 bg-red-950/40 p-2.5 rounded border border-red-900/50 m-0">{modalError}</p>}

                <div className="space-y-2">
                  <label htmlFor="edit-email-input" className="block text-xs font-bold text-zinc-400 uppercase tracking-widest">Email Address</label>
                  <input
                    id="edit-email-input"
                    type="email"
                    value={editEmailVal}
                    onChange={(e) => setEditEmailVal(e.target.value)}
                    className="w-full px-3 py-2 bg-white/[0.04] border border-white/10 rounded-lg text-sm text-white focus:outline-none focus:ring-2 focus:ring-white/20"
                    disabled={saving}
                    required
                  />
                </div>

                <div className="flex justify-end gap-3 pt-2">
                  <button
                    type="button"
                    onClick={closeModal}
                    className="px-4 py-2 text-xs font-semibold text-zinc-400 hover:text-white border border-white/10 rounded-lg hover:bg-white/10 transition-all cursor-pointer"
                    disabled={saving}
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    className="px-4 py-2 bg-white hover:bg-zinc-200 text-black text-xs font-semibold rounded-lg shadow-md transition-all flex items-center gap-1.5 cursor-pointer"
                    disabled={saving}
                  >
                    {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : null}
                    Save Email
                  </button>
                </div>
              </form>
            </div>
          )}

          {/* Withdraw Invitation Modal (Ghosts) */}
          {modalType === 'withdraw' && (
            <div className="w-full max-w-sm bg-[#1c1c1c] border border-white/10 rounded-2xl p-6 shadow-2xl relative">
              <h3 className="text-base font-semibold text-white m-0">Withdraw Invitation</h3>
              <p className="text-xs text-zinc-400 mt-1.5 mb-6">
                Are you sure you want to withdraw the invitation for <strong className="text-white font-semibold">{active?.email}</strong>? This email will no longer be whitelisted.
              </p>

              {modalError && <p className="text-xs text-red-400 bg-red-950/40 p-2.5 rounded border border-red-900/50 mb-4">{modalError}</p>}

              <div className="flex justify-end gap-3">
                <button
                  onClick={closeModal}
                  className="px-4 py-2 text-xs font-semibold text-zinc-400 hover:text-white border border-white/10 rounded-lg hover:bg-white/10 transition-all cursor-pointer"
                  disabled={saving}
                >
                  Cancel
                </button>
                <button
                  onClick={handleWithdrawInvitation}
                  className="px-4 py-2 bg-red-600 hover:bg-red-700 text-white text-xs font-semibold rounded-lg shadow-md transition-all flex items-center gap-1.5 cursor-pointer"
                  disabled={saving}
                >
                  {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Trash className="w-3.5 h-3.5" />}
                  Withdraw
                </button>
              </div>
            </div>
          )}

        </div>
      )}

      {/* New Invitation Modal */}
      <NewInvitationModal
        isOpen={isInviteModalOpen}
        onClose={() => setIsInviteModalOpen(false)}
        initialRole={initialRole}
        onSuccess={fetchRows}
      />
    </div>
  );
}
