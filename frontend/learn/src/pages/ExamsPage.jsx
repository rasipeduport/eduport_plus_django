import { useCallback, useEffect, useState } from 'react';
import { Loader2 } from 'lucide-react';
import api from '../lib/api';
import { useStudent } from '../components/student/student-context';
import { ExamsList } from '../components/exams/exams-list';
import { useRefreshOnFocus } from '../hooks/useRefreshOnFocus';

export default function ExamsPage() {
  const { selectedStudent } = useStudent();
  const [exams, setExams] = useState([]);
  const [additionalExams, setAdditionalExams] = useState([]);
  const [loading, setLoading] = useState(true);

  const fetchExams = useCallback(async () => {
    try {
      const [ex, add] = await Promise.all([api.get('/api/exams/'), api.get('/api/additional-exams/')]);
      setExams(ex.data.exams || []);
      setAdditionalExams(add.data.additional_exams || []);
    } catch (err) {
      console.error('Failed to load exams', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchExams();
  }, [fetchExams, selectedStudent?.id]);

  useRefreshOnFocus(fetchExams);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="h-6 w-6 animate-spin text-primary" />
      </div>
    );
  }

  return (
    <div className="space-y-5 md:space-y-6">
      <section>
        <h1 className="text-text-primary text-xl font-bold md:text-2xl">Exams</h1>
        <p className="text-text-secondary mt-1 text-sm">Chapter and additional exams set by your mentor.</p>
      </section>

      <ExamsList exams={exams} additionalExams={additionalExams} meetLink={selectedStudent?.meet_link} />
    </div>
  );
}
