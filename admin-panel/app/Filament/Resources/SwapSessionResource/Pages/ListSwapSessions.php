<?php

namespace App\Filament\Resources\SwapSessionResource\Pages;

use App\Filament\Resources\SwapSessionResource;
use Filament\Resources\Pages\ListRecords;

class ListSwapSessions extends ListRecords
{
    protected static string $resource = SwapSessionResource::class;

    protected function getHeaderActions(): array
    {
        return [];
    }
}
