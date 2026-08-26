import { DiscoverPageBase } from "@/components/DiscoverFeed";

export const revalidate = 1800;

export default function SchedulePage() {
  return (
    <DiscoverPageBase
      title="Schedule"
      sort="TRENDING_DESC"
      hint="airing this season"
    />
  );
}
