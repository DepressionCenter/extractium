// A small search client, invented for the test suite.
import { Compendium } from "./compendium";

/** One ranked result. */
export interface Result {
  parentId: string;
  score: number;
}

export type Ranker = (results: Result[]) => Result[];

export enum Mode {
  Keyword,
  Semantic,
}

// Ranks results by score, highest first.
export function rank(results: Result[]): Result[] {
  return results.sort((left, right) => right.score - left.score);
}

export class Client {
  private compendium: Compendium;

  constructor(compendium: Compendium) {
    this.compendium = compendium;
  }

  // Runs one query and returns the ranked results.
  search(term: string, mode: Mode = Mode.Keyword): Result[] {
    return rank(this.compendium.lookup(term, mode));
  }
}
