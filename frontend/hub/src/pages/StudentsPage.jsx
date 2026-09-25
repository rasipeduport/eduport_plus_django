import { useCallback, useEffect, useState } from 'react';
import { Loader2 } from 'lucide-react';

import api from '@/lib/api';
import { StudentsTable } from '@/components/students/students-table';

export default function StudentsPage() {
  const [students, setStudents] = useState([]);
  const [role, setRole] = useState('admin');
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
      try {
        const response = await api.get('/api/auth/me/');
        if (active) setRole((response.data.user?.role || 'ADMIN').toLowerCase());
      } catch {
        // Fall back to the admin column set; the API still scopes the rows.
      }
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

      <StudentsTable students={students} role={role} onChanged={fetchStudents} />
    </div>
  );
}
