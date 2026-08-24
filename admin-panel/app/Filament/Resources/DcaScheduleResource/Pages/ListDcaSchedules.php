<?php

namespace App\Filament\Resources\DcaScheduleResource\Pages;

use App\Filament\Resources\DcaScheduleResource;
use Filament\Resources\Pages\ListRecords;

class ListDcaSchedules extends ListRecords
{
    protected static string $resource = DcaScheduleResource::class;

    protected function getHeaderActions(): array
    {
        return [];
    }
}
