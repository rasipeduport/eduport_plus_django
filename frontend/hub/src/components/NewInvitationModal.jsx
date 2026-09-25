import { useState, useEffect, useRef } from 'react';
import { Loader2, Check, X, ChevronDown, Mail, Info } from 'lucide-react';
import api from '../lib/api';

const MEET_URL_REGEX = /^https:\/\/meet\.google\.com\/[a-z]{3}-[a-z]{4}-[a-z]{3}$/;

export default function NewInvitationModal({ isOpen, onClose, initialRole = 'STUDENT', onSuccess }) {
  const [role, setRole] = useState(initialRole);
  const [showRoleDropdown, setShowRoleDropdown] = useState(false);
  const dropdownRef = useRef(null);

  // Form inputs state
  const [email, setEmail] = useState('');
  const [fullName, setFullName] = useState('');
  const [studentCode, setStudentCode] = useState('');

  // Lookup state
  const [verifying, setVerifying] = useState(false);
  const [studentInfo, setStudentInfo] = useState(null);
  const [mentors, setMentors] = useState([]);
  const [tutors, setTutors] = useState([]);
  const [selectedMentor, setSelectedMentor] = useState('');
  const [selectedTutor, setSelectedTutor] = useState('');
  const [meetLink, setMeetLink] = useState('');
  const [whatsappCreated, setWhatsappCreated] = useState(false);

  // Custom dropdown select states for Mentor/Tutor assignment
  const [showMentorDropdown, setShowMentorDropdown] = useState(false);
  const [showTutorDropdown, setShowTutorDropdown] = useState(false);
  const mentorDropdownRef = useRef(null);
  const tutorDropdownRef = useRef(null);

  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [currentUser, setCurrentUser] = useState(null);

  // Sync role state when modal opens or initialRole changes
  useEffect(() => {
    if (isOpen) {
      setRole(initialRole);
      resetForm();
      loadStaffOptions();
    }
  }, [isOpen, initialRole]);

  // Load mentors, tutors and current user info
  const loadStaffOptions = async () => {
    try {
      const [mentorsRes, tutorsRes, meRes] = await Promise.all([
        api.get('/api/mentors/'),
        api.get('/api/tutors/'),
        api.get('/api/auth/me/')
      ]);
      setMentors(mentorsRes.data.mentors || []);
      setTutors(tutorsRes.data.tutors || []);
      setCurrentUser(meRes.data.user);
    } catch (err) {
      console.error('Failed to load mentors/tutors lists', err);
    }
  };

  const resetForm = () => {
    setEmail('');
    setFullName('');
    setStudentCode('');
    setStudentInfo(null);
    setSelectedMentor('');
    setSelectedTutor('');
    setMeetLink('');
    setWhatsappCreated(false);
    setError('');
    setSuccess('');
    setShowRoleDropdown(false);
    setShowMentorDropdown(false);
    setShowTutorDropdown(false);
  };

  // Close dropdowns on clicking outside
  useEffect(() => {
    const handleOutsideClick = (e) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target)) {
        setShowRoleDropdown(false);
      }
      if (mentorDropdownRef.current && !mentorDropdownRef.current.contains(e.target)) {
        setShowMentorDropdown(false);
      }
      if (tutorDropdownRef.current && !tutorDropdownRef.current.contains(e.target)) {
        setShowTutorDropdown(false);
      }
    };
    window.addEventListener('mousedown', handleOutsideClick);
    return () => window.removeEventListener('mousedown', handleOutsideClick);
  }, []);

  const handleLookup = async (e) => {
    e.preventDefault();
    if (!studentCode.trim()) {
      setError('Please enter a student code.');
      return;
    }
    setVerifying(true);
    setError('');
    setSuccess('');
    setStudentInfo(null);

    try {
      const res = await api.post('/api/invitations/lookup-student/', { 
        student_code: studentCode.trim() 
      });
      const data = res.data.student_data;
      setStudentInfo(data);
      setEmail(data.email);
      setFullName(data.full_name);
      setSuccess(`Verified student record: ${data.full_name}`);
      
      // Auto-assign tutor if name matches sheet record
      const sheetTutor = (data.tutor_name || '').trim().toLowerCase();
      if (sheetTutor) {
        const matched = tutors.find(t => (t.full_name || '').trim().toLowerCase() === sheetTutor);
        if (matched) setSelectedTutor(matched.id);
      }
    } catch (err) {
      console.log('LOOKUP_ERROR_RESPONSE:', err.response);
      setError(err.response?.data?.message || 'Student code lookup failed. Verify sheet records.');
    } finally {
      setVerifying(false);
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (role === 'STUDENT' && !studentInfo) {
      setError('Please search and verify student code first.');
      return;
    }
    if (!email.trim()) {
      setError('Please enter a whitelisted email.');
      return;
    }
    if (role === 'STUDENT' && meetLink && !MEET_URL_REGEX.test(meetLink.trim())) {
      setError('Google Meet Link must be valid (e.g. https://meet.google.com/abc-defg-hij).');
      return;
    }

    setSaving(true);
    setError('');
    setSuccess('');

    const payload = {
      role,
      email: email.trim().toLowerCase(),
      full_name: fullName.trim() || email.split('@')[0],
    };

    if (role === 'STUDENT') {
      payload.student_code = studentInfo.student_code;
      payload.mobile_number = studentInfo.mobile_number;
      payload.country = studentInfo.country;
      payload.state = studentInfo.state;
      payload.school_name = studentInfo.school_name;
      payload.grade = studentInfo.grade;
      payload.syllabus = studentInfo.syllabus;
      payload.admission_date = studentInfo.admission_date;
      payload.remarks = studentInfo.remarks;
      payload.mentor_id = selectedMentor || null;
      payload.tutor_id = selectedTutor || null;
      payload.meet_link = meetLink.trim() || null;
    }

    try {
      await api.post('/api/invitations/', payload);
      setSuccess(`Successfully whitelisted invitation for ${payload.full_name}!`);
      setTimeout(() => {
        onSuccess?.();
        onClose();
      }, 1000);
    } catch (err) {
      setError(err.response?.data?.message || 'Failed to create whitelist invitation.');
    } finally {
      setSaving(false);
    }
  };

  if (!isOpen) return null;

  const roleLabel = {
    STUDENT: 'Student',
    MENTOR: 'Mentor',
    TUTOR: 'Tutor',
    ADMIN: 'Admin'
  }[role];

  const isFormValid = role !== 'STUDENT' ? email.trim() : (studentInfo && email.trim() && whatsappCreated);

  const selectedMentorName = mentors.find(m => m.id === selectedMentor)?.full_name || '';
  const selectedTutorName = tutors.find(t => t.id === selectedTutor)?.full_name || '';

  return (
    <div className="legacy-ui fixed inset-0 bg-black/45 flex items-center justify-center z-[100] p-4 animate-fadeIn">
      <div className="w-full max-w-[420px] bg-[#1c1c1c] border border-white/10 rounded-[12px] p-6 shadow-[0_8px_24px_rgba(0,0,0,0.4)] relative">
        
        {/* Close Button */}
        <button 
          onClick={onClose} 
          className="absolute top-6 right-6 p-1.5 rounded-lg hover:bg-white/10 text-zinc-400 hover:text-white transition-all cursor-pointer"
        >
          <X className="w-4 h-4" />
        </button>

        {/* Title */}
        <h2 className="text-[22px] font-bold text-white tracking-tight mt-0 mb-6 leading-[1.2]">Create New Invitation</h2>

        {/* Error / Success Banners */}
        {error && (
          <div className="bg-red-950/40 text-red-400 text-xs p-3 rounded-xl mb-4 border border-red-900/50">
            {error}
          </div>
        )}
        {success && (
          <div className="bg-emerald-950/40 text-emerald-400 text-xs p-3 rounded-xl mb-4 border border-emerald-900/50 flex items-center gap-2 font-medium">
            <Check className="w-4 h-4 shrink-0 text-emerald-400" />
            {success}
          </div>
        )}

        {/* Form Container */}
        <div className="space-y-4">
          
          {/* Custom Role Dropdown */}
          <div className="relative" ref={dropdownRef}>
            <label className="block text-[11px] font-semibold text-white/55 uppercase tracking-[0.08em] mb-2">ROLE</label>
            <button
              type="button"
              onClick={() => setShowRoleDropdown(!showRoleDropdown)}
              disabled={currentUser?.role === 'MENTOR'}
              className="w-full h-[44px] px-3.5 bg-white/[0.06] border border-white/10 hover:border-white/20 rounded-[8px] text-sm text-white flex items-center justify-between transition-all cursor-pointer text-left disabled:opacity-75 disabled:cursor-not-allowed"
            >
              <span>{roleLabel}</span>
              {currentUser?.role !== 'MENTOR' && <ChevronDown className="w-4 h-4 opacity-50" />}
            </button>

            {showRoleDropdown && (
              <div className="absolute left-0 right-0 mt-1 bg-[#1c1c1c] border border-white/10 rounded-[8px] shadow-2xl py-1 z-50 animate-fadeIn">
                {[
                  { key: 'ADMIN', label: 'Admin' },
                  { key: 'MENTOR', label: 'Mentor' },
                  { key: 'TUTOR', label: 'Tutor' },
                  { key: 'STUDENT', label: 'Student' }
                ]
                .filter(opt => {
                  if (currentUser?.role === 'MENTOR') {
                    return opt.key === 'STUDENT';
                  }
                  return true;
                })
                .map(opt => (
                  <button
                    key={opt.key}
                    type="button"
                    onClick={() => {
                      setRole(opt.key);
                      resetForm();
                    }}
                    className={`w-full text-left py-2.5 px-3.5 text-xs transition-colors cursor-pointer hover:bg-white/5 ${role === opt.key ? 'text-white bg-white/10 font-semibold' : 'text-zinc-300 hover:text-white'}`}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Student ID lookup row (Only for STUDENT role) */}
          {role === 'STUDENT' && (
            <div>
              <label htmlFor="student-id-field" className="block text-[11px] font-semibold text-white/55 uppercase tracking-[0.08em] mb-2">STUDENT ID</label>
              <div className="flex gap-2">
                <input
                  id="student-id-field"
                  type="text"
                  placeholder="EDP00099"
                  value={studentCode}
                  onChange={(e) => setStudentCode(e.target.value)}
                  className="flex-1 px-3.5 h-[44px] bg-white/[0.06] border border-white/10 rounded-[8px] text-sm text-white placeholder-zinc-600 uppercase focus:outline-none focus:ring-1 focus:ring-white/20"
                  disabled={verifying || saving}
                />
                <button
                  type="button"
                  onClick={handleLookup}
                  disabled={verifying || saving || !studentCode.trim()}
                  className="h-[44px] w-[90px] bg-white/10 hover:bg-white/20 text-white rounded-[8px] text-sm font-semibold transition-all cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed shrink-0 flex items-center justify-center"
                >
                  {verifying ? <Loader2 className="w-4 h-4 animate-spin" /> : 'Verify'}
                </button>
              </div>
            </div>
          )}

          {/* Non-Student direct invite or Student details entry */}
          {(role !== 'STUDENT' || studentInfo) && (
            <div className="space-y-4 pt-4 border-t border-white/10 animate-fadeIn">
              
              {/* Sheet preview */}
              {studentInfo && (
                <div className="bg-white/[0.03] rounded-lg p-3.5 border border-white/10 grid grid-cols-2 gap-3 text-[11px] leading-relaxed">
                  <div>
                    <span className="text-zinc-500 block">Full Name</span>
                    <span className="text-white font-semibold">{studentInfo.full_name}</span>
                  </div>
                  <div>
                    <span className="text-zinc-500 block">Email Address</span>
                    <span className="text-white font-semibold truncate block" title={studentInfo.email}>{studentInfo.email}</span>
                  </div>
                  <div>
                    <span className="text-zinc-500 block">Grade & Syllabus</span>
                    <span className="text-zinc-300 font-medium">{studentInfo.grade} - {studentInfo.syllabus}</span>
                  </div>
                  <div>
                    <span className="text-zinc-500 block">Tutor (Sheet)</span>
                    <span className="text-zinc-300 font-medium">{studentInfo.tutor_name || '—'}</span>
                  </div>
                </div>
              )}

              {/* Direct email invite inputs (Admins, Mentors, Tutors) */}
              {role !== 'STUDENT' && (
                <div className="space-y-4">
                  <div>
                    <label htmlFor="direct-email" className="block text-[11px] font-semibold text-white/55 uppercase tracking-[0.08em] mb-2">EMAIL</label>
                    <input
                      id="direct-email"
                      type="email"
                      placeholder="user@example.com"
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                      className="w-full px-3.5 h-[44px] bg-white/[0.06] border border-white/10 rounded-[8px] text-sm text-white placeholder-zinc-600 focus:outline-none focus:ring-1 focus:ring-white/20"
                      disabled={saving}
                      required
                    />
                  </div>
                  <div>
                    <label htmlFor="direct-name" className="block text-[11px] font-semibold text-white/55 uppercase tracking-[0.08em] mb-2">FULL NAME</label>
                    <input
                      id="direct-name"
                      type="text"
                      placeholder="Enter Full Name"
                      value={fullName}
                      onChange={(e) => setFullName(e.target.value)}
                      className="w-full px-3.5 h-[44px] bg-white/[0.06] border border-white/10 rounded-[8px] text-sm text-white placeholder-zinc-600 focus:outline-none focus:ring-1 focus:ring-white/20"
                      disabled={saving}
                    />
                  </div>
                </div>
              )}

              {/* Student specific assignments */}
              {role === 'STUDENT' && (
                <div className="space-y-4">
                  
                  {/* Custom Assign Mentor Select */}
                  <div className="relative" ref={mentorDropdownRef}>
                    <label className="block text-[11px] font-semibold text-white/55 uppercase tracking-[0.08em] mb-2">ASSIGN MENTOR</label>
                    <button
                      type="button"
                      onClick={() => setShowMentorDropdown(!showMentorDropdown)}
                      className="w-full h-[44px] px-3.5 bg-white/[0.06] border border-white/10 hover:border-white/20 rounded-[8px] text-sm text-white flex items-center justify-between transition-all cursor-pointer text-left"
                    >
                      <span className="truncate">{selectedMentorName || 'Select Mentor...'}</span>
                      <ChevronDown className="w-4 h-4 opacity-50 shrink-0" />
                    </button>

                    {showMentorDropdown && (
                      <div className="absolute left-0 right-0 mt-1 bg-[#1c1c1c] border border-white/10 rounded-[8px] shadow-2xl py-1 z-50 max-h-52 overflow-y-auto">
                        <button
                          type="button"
                          onClick={() => {
                            setSelectedMentor('');
                            setShowMentorDropdown(false);
                          }}
                          className="w-full text-left py-2.5 px-3.5 text-xs text-zinc-400 hover:bg-white/5 hover:text-white"
                        >
                          Unassigned
                        </button>
                        {mentors.map(m => (
                          <button
                            key={m.id}
                            type="button"
                            onClick={() => {
                              setSelectedMentor(m.id);
                              setShowMentorDropdown(false);
                            }}
                            className={`w-full text-left py-2.5 px-3.5 text-xs transition-colors cursor-pointer hover:bg-white/5 ${selectedMentor === m.id ? 'text-white bg-white/10 font-semibold' : 'text-zinc-300 hover:text-white'}`}
                          >
                            {m.full_name || m.email}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>

                  {/* Custom Assign Tutor Select */}
                  <div className="relative" ref={tutorDropdownRef}>
                    <label className="block text-[11px] font-semibold text-white/55 uppercase tracking-[0.08em] mb-2">ASSIGN TUTOR</label>
                    <button
                      type="button"
                      onClick={() => setShowTutorDropdown(!showTutorDropdown)}
                      className="w-full h-[44px] px-3.5 bg-white/[0.06] border border-white/10 hover:border-white/20 rounded-[8px] text-sm text-white flex items-center justify-between transition-all cursor-pointer text-left"
                    >
                      <span className="truncate">{selectedTutorName || 'Select Tutor...'}</span>
                      <ChevronDown className="w-4 h-4 opacity-50 shrink-0" />
                    </button>

                    {showTutorDropdown && (
                      <div className="absolute left-0 right-0 mt-1 bg-[#1c1c1c] border border-white/10 rounded-[8px] shadow-2xl py-1 z-50 max-h-52 overflow-y-auto">
                        <button
                          type="button"
                          onClick={() => {
                            setSelectedTutor('');
                            setShowTutorDropdown(false);
                          }}
                          className="w-full text-left py-2.5 px-3.5 text-xs text-zinc-400 hover:bg-white/5 hover:text-white"
                        >
                          Unassigned
                        </button>
                        {tutors.map(t => (
                          <button
                            key={t.id}
                            type="button"
                            onClick={() => {
                              setSelectedTutor(t.id);
                              setShowTutorDropdown(false);
                            }}
                            className={`w-full text-left py-2.5 px-3.5 text-xs transition-colors cursor-pointer hover:bg-white/5 ${selectedTutor === t.id ? 'text-white bg-white/10 font-semibold' : 'text-zinc-300 hover:text-white'}`}
                          >
                            {t.full_name || t.email}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>

                  {/* Meet Link */}
                  <div>
                    <label htmlFor="student-meet-link" className="block text-[11px] font-semibold text-white/55 uppercase tracking-[0.08em] mb-2">GOOGLE MEET LINK</label>
                    <input
                      id="student-meet-link"
                      type="url"
                      placeholder="https://meet.google.com/abc-defg-hij"
                      value={meetLink}
                      onChange={(e) => setMeetLink(e.target.value)}
                      className="w-full px-3.5 h-[44px] bg-white/[0.06] border border-white/10 rounded-[8px] text-sm text-white placeholder-zinc-600 focus:outline-none focus:ring-1 focus:ring-white/20"
                      required
                    />
                    <p className="text-[11px] text-zinc-400 mt-2 m-0 leading-relaxed flex items-start gap-1.5">
                      <Info className="w-3.5 h-3.5 text-zinc-400 mt-0.5 shrink-0" />
                      <span> Classroom setting should be set to <strong>Open</strong> so the student can connect.</span>
                    </p>
                  </div>

                  {/* WhatsApp Checkbox */}
                  <label className="flex items-start gap-3 select-none cursor-pointer mt-1 bg-white/[0.03] p-3.5 rounded-lg border border-white/10 hover:bg-white/[0.06] transition-colors">
                    <input
                      type="checkbox"
                      checked={whatsappCreated}
                      onChange={(e) => setWhatsappCreated(e.target.checked)}
                      className="mt-0.5 h-4 w-4 rounded border-white/20 bg-black/25 text-white focus:ring-white/20 cursor-pointer"
                      required
                    />
                    <span className="text-xs text-zinc-400 leading-normal">
                      Have you created the WhatsApp group for this student? (Required to submit)
                    </span>
                  </label>
                </div>
              )}

              {/* Submit Button */}
              <button
                onClick={handleSubmit}
                disabled={saving || !isFormValid}
                className={`w-full h-[44px] rounded-[8px] text-sm font-semibold shadow-md transition-all flex items-center justify-center gap-2 cursor-pointer mt-2 ${isFormValid ? 'bg-white text-black hover:bg-zinc-200' : 'bg-white/10 text-white/40 cursor-not-allowed'}`}
              >
                {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Mail className="w-4 h-4" />}
                Create Invitation
              </button>

            </div>
          )}

        </div>

      </div>
    </div>
  );
}
