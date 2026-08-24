<?php

namespace App\Filament\Resources\RiskEventResource\Pages;

use App\Filament\Resources\RiskEventResource;
use Filament\Resources\Pages\ListRecords;

class ListRiskEvents extends ListRecords
{
    protected static string $resource = RiskEventResource::class;

    protected function getHeaderActions(): array
    {
        return [];
    }
}
