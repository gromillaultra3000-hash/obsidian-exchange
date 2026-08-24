<?php

namespace App\Filament\Resources\LimitOrderResource\Pages;

use App\Filament\Resources\LimitOrderResource;
use Filament\Resources\Pages\ListRecords;

class ListLimitOrders extends ListRecords
{
    protected static string $resource = LimitOrderResource::class;

    protected function getHeaderActions(): array
    {
        return [];
    }
}
