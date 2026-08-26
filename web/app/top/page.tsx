import { DiscoverPageBase } from "@/components/DiscoverFeed";

export const revalidate = 600;

export default function TopPage() {
  return (
    <DiscoverPageBase
      title="Top Anime"
      sort="SCORE_DESC"
      hint="highest rated of all time"
    />
  );
}
