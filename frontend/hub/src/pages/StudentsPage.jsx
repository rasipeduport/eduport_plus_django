import { useCallback, useEffect, useState } from 'react';
import { Loader2 } from 'lucide-react';

import api from '@/lib/api';
import { StudentsTable } from '@/components/students/students-table';

// `role` is the caller's Hub role (App.jsx, lib/access hubRole); it picks the
// column set and actions, while the API decides which rows come back.
export default function StudentsPage({ role }) {
  const [students, setStudents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const fetchStudents = useCallback(async () => {
    setError('');
    try {
      const response = await api.get('/api/students/');
      setStudents(response.data);
    } catch (err) {
      setError(err.response?.data?.message || 'Failed to load students list.');
    }
  }, []);

  useEffect(() => {
    let active = true;

    (async () => {
      await fetchStudents();
      if (active) setLoading(false);
    })();

    return () => {
      active = false;
    };
  }, [fetchStudents]);

  if (loading) {
    return (
      <div className="flex h-96 items-center justify-center">
        <Loader2 className="text-muted-foreground size-8 animate-spin" />
      </div>
    );
  }

  return (
    <div className="container mx-auto px-4 py-16">
      {error && <p className="text-destructive mb-4 text-sm">{error}</p>}

      <StudentsTable students={students} role={role.toLowerCase()} onChanged={fetchStudents} />
    </div>
  );
}
