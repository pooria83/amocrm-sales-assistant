import {
  ToggleGroup,
  ToggleGroupItem,
} from '@/components/ui/toggle-group'
import type { Lang } from '@/lib/types'
import { useI18n } from '@/i18n'

export function LanguageToggle() {
  const { lang, setLang } = useI18n()
  return (
    <ToggleGroup
      type="single"
      value={lang}
      onValueChange={(value) => value && setLang(value as Lang)}
      data-testid="language-toggle"
      className="gap-0 overflow-hidden rounded-md border border-[#d5dbe2]"
    >
      <ToggleGroupItem
        value="ru"
        data-testid="lang-ru"
        aria-label="Русский"
        className="h-7 rounded-none px-2.5 text-xs data-[state=on]:bg-[#2f80ed] data-[state=on]:text-white"
      >
        RU
      </ToggleGroupItem>
      <ToggleGroupItem
        value="en"
        data-testid="lang-en"
        aria-label="English"
        className="h-7 rounded-none px-2.5 text-xs data-[state=on]:bg-[#2f80ed] data-[state=on]:text-white"
      >
        EN
      </ToggleGroupItem>
    </ToggleGroup>
  )
}
