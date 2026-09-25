import { MonitorIcon, MoonIcon, SunIcon } from 'lucide-react';
import { useTheme } from 'next-themes';

import { Button } from '@/components/ui/button';
import { ButtonGroup } from '@/components/ui/button-group';

export default function ThemeToggle() {
  const { theme, setTheme } = useTheme();

  return (
    <ButtonGroup orientation="horizontal" aria-label="Theme" className="h-fit w-full">
      <Button
        variant="outline"
        size="icon-sm"
        className="flex-1"
        disabled={theme === 'system'}
        onClick={() => setTheme('system')}
      >
        <MonitorIcon />
      </Button>
      <Button
        variant="outline"
        size="icon-sm"
        className="flex-1"
        disabled={theme === 'light'}
        onClick={() => setTheme('light')}
      >
        <SunIcon />
      </Button>
      <Button
        variant="outline"
        size="icon-sm"
        className="flex-1"
        disabled={theme === 'dark'}
        onClick={() => setTheme('dark')}
      >
        <MoonIcon />
      </Button>
    </ButtonGroup>
  );
}
