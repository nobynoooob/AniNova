import { DiscoverPageBase } from "@/components/DiscoverFeed";

export const revalidate = 600;

export default function MoviesPage() {
  return (
    <DiscoverPageBase
      title="Movies"
      sort="POPULARITY_DESC"
      hint="anime films"
    />
  );
}
